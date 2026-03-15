"""
Video source adapter.

Treats a video as a sequence of images. Samples frames at an adaptive rate
(higher for short videos, lower for long videos) and deduplicates consecutive
similar frames using perceptual hashing. For each unique frame:

  1. Run EasyOCR to extract visible text.
  2. If OCR yields > 100 characters → use that as the frame's content.
  3. Otherwise → call a vision LLM to describe the frame.

Sampled frames are saved as JPEG files; a metadata.json is written alongside
them in the data directory.

Adaptive sampling rates:
  < 1 min   → 2 fps
  1–5 min   → 1 fps
  5–15 min  → 0.5 fps (every 2 s)
  > 15 min  → 0.25 fps (every 4 s)

Usage:
    from app.sources.video import VideoSource

    docs = VideoSource().fetch("/path/to/lecture.mp4")
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from langchain_core.documents import Document

from app.sources.base import resolve_data_dir

if TYPE_CHECKING:
    pass

# Perceptual hash distance threshold — frames with distance < this are considered
# duplicates and skipped. Lower = stricter deduplication.
_PHASH_THRESHOLD = 8

# Minimum OCR text length to skip LLM vision call
_OCR_TEXT_MIN_LEN = 100


def _adaptive_sample_interval(duration_seconds: float) -> float:
    """Return the frame sampling interval in seconds for a given video duration."""
    minutes = duration_seconds / 60.0
    if minutes < 1:
        return 0.5   # 2 fps
    if minutes < 5:
        return 1.0   # 1 fps
    if minutes < 15:
        return 2.0   # 0.5 fps
    return 4.0       # 0.25 fps


def _cv2_frame_to_pil(frame):
    """Convert an OpenCV BGR frame to a PIL Image."""
    from PIL import Image
    import cv2

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)


def _phash(pil_image) -> object:
    """Return the perceptual hash of a PIL image."""
    import imagehash

    return imagehash.phash(pil_image)


# ── EasyOCR reader (lazy singleton) ──────────────────────────────────────────

_ocr_reader = None


def _get_ocr_reader(lang: list[str] | None = None):
    global _ocr_reader
    if _ocr_reader is None:
        import easyocr

        _ocr_reader = easyocr.Reader(lang or ["en"], gpu=False, verbose=False)
    return _ocr_reader


def _run_ocr(frame_array) -> str:
    """Run EasyOCR on an OpenCV BGR frame array and return concatenated text."""
    reader = _get_ocr_reader()
    results = reader.readtext(frame_array, detail=0)
    return " ".join(str(r).strip() for r in results if str(r).strip())


def _describe_frame_with_llm(pil_image, llm_config: dict | None) -> str:
    """Use a vision LLM to describe a single frame (PIL Image)."""
    import base64
    import io

    from langchain_core.messages import HumanMessage

    from app.config import get_llm

    buf = io.BytesIO()
    pil_image.save(buf, format="JPEG", quality=85)
    b64 = base64.standard_b64encode(buf.getvalue()).decode("ascii")

    llm = get_llm(llm_config)
    message = HumanMessage(
        content=[
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            },
            {
                "type": "text",
                "text": (
                    "Describe what is shown in this video frame in 1-3 sentences. "
                    "Focus on the main content, any diagrams, text on screen, "
                    "or notable visual elements."
                ),
            },
        ]
    )
    response = llm.invoke([message])
    return response.content if hasattr(response, "content") else str(response)


# ── Public API ────────────────────────────────────────────────────────────────

class VideoSource:
    """Source adapter for local video files."""

    def fetch(
        self,
        path: str,
        *,
        llm_config: dict | None = None,
        ocr_languages: list[str] | None = None,
        username: str = "default",
        collection_name: str = "sample",
    ) -> list[Document]:
        """
        Process a local video file and return a Document per unique frame.

        Parameters
        ----------
        path            : local path to the video file
        llm_config      : LLM configuration dict; must be a vision-capable model
                          if any frames lack sufficient OCR text.
        ocr_languages   : EasyOCR language codes (default: ["en"])
        username        : user namespace for data storage
        collection_name : collection namespace for data storage

        Returns
        -------
        list[Document]  one Document per unique (non-duplicate) sampled frame;
                        page_content is OCR text or LLM description;
                        metadata includes frame_index, timestamp_seconds,
                        frame_path, content_source ("ocr" | "llm").
        """
        import cv2

        video_path = Path(path).resolve()
        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found: {path!r}")

        # ── Set up output directory ───────────────────────────────────────────
        data_dir = resolve_data_dir(username, collection_name)
        frames_dir = data_dir / "video" / video_path.stem
        frames_dir.mkdir(parents=True, exist_ok=True)

        # ── Open video ────────────────────────────────────────────────────────
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise RuntimeError(
                f"Cannot open video: {video_path}\n"
                "Tip: if the file is audio-only (e.g. an MP4 with no video track), "
                "use AudioSource instead."
            )

        fps: float = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames: int = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration_seconds: float = total_frames / fps if fps > 0 else 0.0

        sample_interval = _adaptive_sample_interval(duration_seconds)
        # How many video frames to skip between samples
        frame_step = max(1, int(round(fps * sample_interval)))

        documents: list[Document] = []
        frame_metadata_list: list[dict] = []
        last_hash = None
        saved_frame_idx = 0

        frame_pos = 0
        while True:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_pos)
            ret, frame = cap.read()
            if not ret:
                break

            timestamp = frame_pos / fps
            pil_img = _cv2_frame_to_pil(frame)
            current_hash = _phash(pil_img)

            # Duplicate frame detection
            if last_hash is not None:
                distance = current_hash - last_hash
                if distance < _PHASH_THRESHOLD:
                    frame_pos += frame_step
                    continue

            last_hash = current_hash

            # ── Save frame JPEG ───────────────────────────────────────────────
            frame_filename = f"frame_{saved_frame_idx:05d}.jpg"
            frame_path = frames_dir / frame_filename
            pil_img.save(str(frame_path), format="JPEG", quality=85)

            # ── OCR first ────────────────────────────────────────────────────
            ocr_text = _run_ocr(frame)
            if len(ocr_text) >= _OCR_TEXT_MIN_LEN:
                content = ocr_text
                content_source = "ocr"
            else:
                # Fall back to vision LLM description
                try:
                    content = _describe_frame_with_llm(pil_img, llm_config)
                    content_source = "llm"
                except Exception:
                    # If LLM fails and we have any OCR text, use it
                    content = ocr_text or f"[Frame at {timestamp:.1f}s - no description available]"
                    content_source = "ocr_fallback"

            frame_meta = {
                "frame_index": saved_frame_idx,
                "timestamp_seconds": round(timestamp, 3),
                "frame_path": str(frame_path),
                "content_source": content_source,
                "source_url": str(video_path),
                "source_type": "video",
            }
            frame_metadata_list.append(frame_meta)
            documents.append(Document(page_content=content, metadata=frame_meta))

            saved_frame_idx += 1
            frame_pos += frame_step

        cap.release()

        # ── Write metadata.json ───────────────────────────────────────────────
        summary = {
            "source_path": str(video_path),
            "duration_seconds": round(duration_seconds, 2),
            "total_video_frames": total_frames,
            "sample_interval_seconds": sample_interval,
            "unique_frames_saved": saved_frame_idx,
            "frames": frame_metadata_list,
        }
        with open(frames_dir / "metadata.json", "w", encoding="utf-8") as fh:
            json.dump(summary, fh, ensure_ascii=False, indent=2)

        return documents

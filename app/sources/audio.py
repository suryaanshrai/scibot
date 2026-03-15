"""
Audio source adapter.

Transcribes a local audio file to text using faster-whisper (CTranslate2-based
Whisper), which runs fully locally — no API calls are made.

Supported formats: anything ffmpeg can read (mp3, wav, ogg, m4a, flac, …).

Usage:
    from app.sources.audio import AudioSource

    docs = AudioSource().fetch("/path/to/lecture.mp3")
    docs = AudioSource(model_size="large-v3").fetch("/path/to/interview.wav")
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from langchain_core.documents import Document

from app.sources.base import resolve_data_dir


class AudioSource:
    """Source adapter for local audio files using faster-whisper STT."""

    def __init__(self, model_size: str = "base", device: str = "auto") -> None:
        """
        Parameters
        ----------
        model_size : Whisper model size — "tiny" | "base" | "small" | "medium" |
                     "large-v2" | "large-v3" (default: "base").
                     Larger models are slower but more accurate.
        device     : "cpu" | "cuda" | "auto" (default: "auto" — uses CUDA if available).
        """
        self._model_size = model_size
        self._device = device
        self._model = None  # lazy-loaded on first use

    def _get_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            device = self._device
            if device == "auto":
                try:
                    import torch
                    device = "cuda" if torch.cuda.is_available() else "cpu"
                except ImportError:
                    device = "cpu"

            compute_type = "float16" if device == "cuda" else "int8"
            self._model = WhisperModel(
                self._model_size,
                device=device,
                compute_type=compute_type,
            )
        return self._model

    def fetch(
        self,
        path: str,
        *,
        username: str = "default",
        collection_name: str = "sample",
        beam_size: int = 5,
    ) -> list[Document]:
        """
        Transcribe a local audio file and return its content as a Document.

        Parameters
        ----------
        path            : local file path to the audio file
        username        : user namespace for data storage
        collection_name : collection namespace for data storage
        beam_size       : beam search width (higher = more accurate, slower)

        Returns
        -------
        list[Document]  a single-element list; the Document's page_content is the
                        full transcript text, and metadata includes:
                          source_url, source_type, language, duration_seconds,
                          word_count, model_size.
        """
        audio_path = Path(path).resolve()
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {path!r}")

        model = self._get_model()
        segments, info = model.transcribe(str(audio_path), beam_size=beam_size)

        # Collect all segment texts
        text_parts: list[str] = []
        for segment in segments:
            text_parts.append(segment.text.strip())

        transcript = " ".join(text_parts).strip()
        language = info.language
        duration = info.duration  # seconds

        metadata = {
            "source_url": str(audio_path),
            "source_type": "audio",
            "language": language,
            "duration_seconds": round(duration, 2),
            "word_count": len(transcript.split()),
            "model_size": self._model_size,
        }

        # ── Persist transcript ────────────────────────────────────────────────
        data_dir = resolve_data_dir(username, collection_name)
        audio_dir = data_dir / "audio"
        audio_dir.mkdir(exist_ok=True)

        stem = audio_path.stem
        sidecar = {
            "source_path": str(audio_path),
            "transcript": transcript,
            **metadata,
        }
        sidecar_path = audio_dir / f"{stem}.json"
        with open(sidecar_path, "w", encoding="utf-8") as fh:
            json.dump(sidecar, fh, ensure_ascii=False, indent=2)

        metadata["sidecar_path"] = str(sidecar_path)
        return [Document(page_content=transcript, metadata=metadata)]

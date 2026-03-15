"""
Image source adapter.

Processes a local image file and returns its content as a Document.
Uses a vision-capable LLM (e.g. GPT-4o, Claude, Gemini) to:
  1. Generate a natural-language description of the image.
  2. Extract any text visible in the image (OCR via LLM).

If the caller already provides a description, the LLM is only asked to extract
visible text (saving tokens). The original image file stays in place; a sidecar
JSON is saved in the data directory.

Usage:
    from app.sources.image import ImageSource

    docs = ImageSource().fetch("/path/to/figure.png")
    docs = ImageSource().fetch("/path/to/figure.png", description="Flow diagram of...")
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage

from app.config import get_llm
from app.sources.base import resolve_data_dir


def _encode_image(path: Path) -> tuple[str, str]:
    """Return (base64_data, media_type) for the image at *path*."""
    suffix = path.suffix.lower()
    media_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }
    media_type = media_map.get(suffix, "image/jpeg")
    with open(path, "rb") as fh:
        data = base64.standard_b64encode(fh.read()).decode("ascii")
    return data, media_type


def _call_vision_llm(
    image_path: Path,
    prompt: str,
    llm_config: dict | None,
) -> str:
    """Send a vision prompt with the image to the configured LLM and return the text reply."""
    llm = get_llm(llm_config)
    b64, media_type = _encode_image(image_path)
    message = HumanMessage(
        content=[
            {
                "type": "image_url",
                "image_url": {"url": f"data:{media_type};base64,{b64}"},
            },
            {"type": "text", "text": prompt},
        ]
    )
    response = llm.invoke([message])
    return response.content if hasattr(response, "content") else str(response)


_DESCRIBE_AND_OCR_PROMPT = (
    "You are analyzing an image. Please provide:\n"
    "1. A clear, concise description of what the image shows (2-4 sentences).\n"
    "2. A verbatim transcription of ALL text visible in the image "
    "(labels, captions, UI text, equations, etc.). If there is no text, write 'None'.\n\n"
    "Respond in this exact JSON format:\n"
    '{"description": "...", "image_text": "..."}'
)

_OCR_ONLY_PROMPT = (
    "Extract ALL text visible in this image verbatim — labels, captions, equations, "
    "UI elements, etc. If there is no text, reply with 'None'.\n\n"
    "Respond in this exact JSON format:\n"
    '{"image_text": "..."}'
)


def _parse_json_response(raw: str, keys: list[str]) -> dict[str, str]:
    """Extract JSON from an LLM response, tolerating markdown code fences."""
    import re

    raw = raw.strip()
    raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\n?```$", "", raw, flags=re.MULTILINE)
    try:
        parsed = json.loads(raw)
        return {k: str(parsed.get(k, "")).strip() for k in keys}
    except Exception:
        # Fallback: return raw text as the first key
        return {keys[0]: raw.strip()}


class ImageSource:
    """Source adapter for local image files using a vision LLM."""

    def fetch(
        self,
        path: str,
        *,
        description: str | None = None,
        llm_config: dict | None = None,
        username: str = "default",
        collection_name: str = "sample",
    ) -> list[Document]:
        """
        Analyse an image and return its content as a Document.

        Parameters
        ----------
        path            : local path to the image file
        description     : optional user-supplied description; if provided the LLM
                          is only asked to extract visible text (not re-describe).
        llm_config      : LLM configuration dict (see app.config.get_llm).
                          Must point to a vision-capable model.
        username        : user namespace for data storage
        collection_name : collection namespace for data storage

        Returns
        -------
        list[Document]  single-element list; page_content is the description
                        combined with any extracted text, metadata includes
                        source_path, description, image_text, source_type.
        """
        image_path = Path(path).resolve()
        if not image_path.exists():
            raise FileNotFoundError(f"Image file not found: {path!r}")

        # ── LLM analysis ──────────────────────────────────────────────────────
        if description:
            # Only run OCR — description already provided
            raw = _call_vision_llm(image_path, _OCR_ONLY_PROMPT, llm_config)
            parsed = _parse_json_response(raw, ["image_text"])
            image_text = parsed.get("image_text", "").strip()
            if image_text.lower() in ("none", ""):
                image_text = ""
        else:
            raw = _call_vision_llm(image_path, _DESCRIBE_AND_OCR_PROMPT, llm_config)
            parsed = _parse_json_response(raw, ["description", "image_text"])
            description = parsed.get("description", "").strip()
            image_text = parsed.get("image_text", "").strip()
            if image_text.lower() in ("none", ""):
                image_text = ""

        # Build document content
        content_parts = [description]
        if image_text:
            content_parts.append(f"Visible text:\n{image_text}")
        page_content = "\n\n".join(p for p in content_parts if p)

        metadata = {
            "source_path": str(image_path),
            "source_type": "image",
            "description": description,
            "image_text": image_text,
        }

        # ── Persist sidecar JSON ──────────────────────────────────────────────
        data_dir = resolve_data_dir(username, collection_name)
        images_dir = data_dir / "images"
        images_dir.mkdir(exist_ok=True)

        sidecar = {
            "source_path": str(image_path),
            "description": description,
            "image_text": image_text,
        }
        sidecar_path = images_dir / f"{image_path.stem}.json"
        with open(sidecar_path, "w", encoding="utf-8") as fh:
            json.dump(sidecar, fh, ensure_ascii=False, indent=2)

        metadata["sidecar_path"] = str(sidecar_path)
        return [Document(page_content=page_content, metadata=metadata)]

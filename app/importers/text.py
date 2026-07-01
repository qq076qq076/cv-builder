from __future__ import annotations

from pathlib import Path


SUPPORTED_TEXT_SUFFIXES = {".txt", ".md", ".markdown"}


def can_extract_text(filename: str) -> bool:
    return Path(filename).suffix.lower() in SUPPORTED_TEXT_SUFFIXES


def extract_text_from_bytes(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "utf-16", "big5"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue

    return content.decode("utf-8", errors="replace")


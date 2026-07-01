from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader


def can_extract_pdf(filename: str, content_type: str | None) -> bool:
    return filename.lower().endswith(".pdf") or content_type == "application/pdf"


def extract_text_from_pdf_bytes(content: bytes) -> str:
    reader = PdfReader(BytesIO(content))
    page_texts = []

    for page in reader.pages:
        page_text = page.extract_text() or ""
        if page_text.strip():
            page_texts.append(page_text.strip())

    return "\n\n".join(page_texts)

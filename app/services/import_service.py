from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.importers.text import can_extract_text, extract_text_from_bytes
from app.schemas.evidence import EvidenceSource
from app.storage.evidence import EvidenceRepository
from app.storage.workspace import ensure_workspace_dirs


@dataclass(frozen=True)
class SavedUpload:
    source: EvidenceSource
    saved_path: Path
    extracted_text: str | None = None


class ImportService:
    def __init__(self, workspace_path: Path) -> None:
        self.workspace_path = workspace_path
        self.evidence_repository = EvidenceRepository(workspace_path)

    def save_uploaded_file(
        self,
        *,
        filename: str,
        content_type: str | None,
        content: bytes,
    ) -> SavedUpload:
        ensure_workspace_dirs(self.workspace_path)

        source_id = f"src_{uuid.uuid4().hex}"
        safe_filename = _safe_filename(filename)
        relative_path = Path("evidence/files") / f"{source_id}_{safe_filename}"
        saved_path = self.workspace_path / relative_path
        saved_path.parent.mkdir(parents=True, exist_ok=True)
        saved_path.write_bytes(content)

        extracted_text_path: str | None = None
        extraction_status = "not_supported"
        extracted_text: str | None = None

        if can_extract_text(filename):
            extracted_text = extract_text_from_bytes(content)
            extracted_relative_path = Path("evidence/extracted") / f"{source_id}.txt"
            extracted_path = self.workspace_path / extracted_relative_path
            extracted_path.parent.mkdir(parents=True, exist_ok=True)
            extracted_path.write_text(extracted_text, encoding="utf-8")
            extracted_text_path = extracted_relative_path.as_posix()
            extraction_status = "completed"

        source = EvidenceSource(
            id=source_id,
            label=filename,
            path=relative_path.as_posix(),
            originalFilename=filename,
            contentType=content_type,
            sizeBytes=len(content),
            extractedTextPath=extracted_text_path,
            extractionStatus=extraction_status,
            createdAt=datetime.now(timezone.utc),
        )
        self.evidence_repository.add_source(source)

        return SavedUpload(source=source, saved_path=saved_path, extracted_text=extracted_text)


def _safe_filename(filename: str) -> str:
    path_name = Path(filename).name.strip()
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", path_name)
    normalized = normalized.strip(".-")
    return normalized or "upload"

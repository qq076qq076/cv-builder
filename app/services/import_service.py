from __future__ import annotations

import re
from hashlib import sha256
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.importers.pdf import can_extract_pdf, extract_text_from_pdf_bytes
from app.importers.text import can_extract_text, extract_text_from_bytes
from app.schemas.evidence import EvidenceSource
from app.storage.evidence import EvidenceRepository
from app.storage.workspace import ensure_workspace_dirs


@dataclass(frozen=True)
class SavedUpload:
    source: EvidenceSource
    saved_path: Path
    extracted_text: str | None = None
    is_duplicate: bool = False


@dataclass(frozen=True)
class ExtractionResult:
    text: str | None
    status: str


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

        content_hash = sha256(content).hexdigest()
        existing_source = self._find_existing_source(content_hash)
        if existing_source is not None:
            return SavedUpload(
                source=existing_source,
                saved_path=self.workspace_path / existing_source.path,
                extracted_text=_read_existing_extracted_text(self.workspace_path, existing_source),
                is_duplicate=True,
            )

        source_id = f"src_{uuid.uuid4().hex}"
        safe_filename = _safe_filename(filename)
        relative_path = Path("evidence/files") / f"{source_id}_{safe_filename}"
        saved_path = self.workspace_path / relative_path
        saved_path.parent.mkdir(parents=True, exist_ok=True)
        saved_path.write_bytes(content)

        extraction_result = _extract_source_text(
            filename=filename,
            content_type=content_type,
            content=content,
        )
        extracted_text_path = _write_extracted_text(
            self.workspace_path,
            source_id,
            extraction_result.text,
        )

        source = EvidenceSource(
            id=source_id,
            label=filename,
            path=relative_path.as_posix(),
            originalFilename=filename,
            contentType=content_type,
            sizeBytes=len(content),
            contentHash=content_hash,
            extractedTextPath=extracted_text_path,
            extractionStatus=extraction_result.status,
            createdAt=datetime.now(timezone.utc),
        )
        self.evidence_repository.add_source(source)

        return SavedUpload(source=source, saved_path=saved_path, extracted_text=extraction_result.text)

    def reprocess_source(self, source_id: str) -> SavedUpload | None:
        ensure_workspace_dirs(self.workspace_path)

        source = self.evidence_repository.get_source(source_id)
        if source is None:
            return None

        saved_path = self.workspace_path / source.path
        if not saved_path.is_file():
            updated_source = source.model_copy(update={"extraction_status": "missing_file"})
            self.evidence_repository.update_source(updated_source)
            return SavedUpload(source=updated_source, saved_path=saved_path)

        content = saved_path.read_bytes()
        content_hash = source.content_hash or sha256(content).hexdigest()
        extraction_result = _extract_source_text(
            filename=source.original_filename,
            content_type=source.content_type,
            content=content,
        )
        extracted_text_path = _write_extracted_text(
            self.workspace_path,
            source.id,
            extraction_result.text,
        )
        updated_source = source.model_copy(
            update={
                "content_hash": content_hash,
                "extracted_text_path": extracted_text_path,
                "extraction_status": extraction_result.status,
                "size_bytes": len(content),
            }
        )
        self.evidence_repository.update_source(updated_source)

        return SavedUpload(
            source=updated_source,
            saved_path=saved_path,
            extracted_text=extraction_result.text,
        )

    def _find_existing_source(self, content_hash: str) -> EvidenceSource | None:
        source_with_hash = self.evidence_repository.find_by_content_hash(content_hash)
        if source_with_hash is not None:
            return source_with_hash

        for source in self.evidence_repository.list_sources().sources:
            if source.content_hash is not None:
                continue
            if _hash_file(self.workspace_path / source.path) == content_hash:
                return source

        return None


def _safe_filename(filename: str) -> str:
    path_name = Path(filename).name.strip()
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", path_name)
    normalized = normalized.strip(".-")
    return normalized or "upload"


def _hash_file(path: Path) -> str | None:
    if not path.is_file():
        return None

    return sha256(path.read_bytes()).hexdigest()


def _extract_source_text(
    *,
    filename: str,
    content_type: str | None,
    content: bytes,
) -> ExtractionResult:
    if can_extract_text(filename):
        return ExtractionResult(text=extract_text_from_bytes(content), status="completed")

    if can_extract_pdf(filename, content_type):
        try:
            extracted_text = extract_text_from_pdf_bytes(content)
        except Exception:
            return ExtractionResult(text=None, status="failed")

        status = "completed" if extracted_text.strip() else "empty"
        return ExtractionResult(text=extracted_text, status=status)

    return ExtractionResult(text=None, status="not_supported")


def _write_extracted_text(
    workspace_path: Path,
    source_id: str,
    extracted_text: str | None,
) -> str | None:
    if extracted_text is None:
        return None

    extracted_relative_path = Path("evidence/extracted") / f"{source_id}.txt"
    extracted_path = workspace_path / extracted_relative_path
    extracted_path.parent.mkdir(parents=True, exist_ok=True)
    extracted_path.write_text(extracted_text, encoding="utf-8")
    return extracted_relative_path.as_posix()


def _read_existing_extracted_text(
    workspace_path: Path,
    source: EvidenceSource,
) -> str | None:
    if source.extracted_text_path is None:
        return None

    extracted_path = workspace_path / source.extracted_text_path
    if not extracted_path.is_file():
        return None

    return extracted_path.read_text(encoding="utf-8")

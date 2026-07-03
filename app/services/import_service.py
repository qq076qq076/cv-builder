from __future__ import annotations

import re
from hashlib import sha256
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from urllib.parse import urlparse

from app.schemas.evidence import EvidenceSource
from app.storage.evidence import EvidenceRepository
from app.storage.workspace import ensure_workspace_dirs


@dataclass(frozen=True)
class SavedUpload:
    source: EvidenceSource
    saved_path: Path
    is_duplicate: bool = False


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
                is_duplicate=True,
            )

        source_id = f"src_{uuid.uuid4().hex}"
        safe_filename = _safe_filename(filename)
        relative_path = Path("evidence/files") / f"{source_id}_{safe_filename}"
        saved_path = self.workspace_path / relative_path
        saved_path.parent.mkdir(parents=True, exist_ok=True)
        saved_path.write_bytes(content)

        source = EvidenceSource(
            id=source_id,
            label=filename,
            path=relative_path.as_posix(),
            originalFilename=filename,
            contentType=content_type,
            sizeBytes=len(content),
            contentHash=content_hash,
            extractionStatus="not_required",
            createdAt=datetime.now(timezone.utc),
        )
        self.evidence_repository.add_source(source)

        return SavedUpload(source=source, saved_path=saved_path)

    def save_url_source(self, *, url: str, label: str | None = None) -> SavedUpload:
        ensure_workspace_dirs(self.workspace_path)

        normalized_url = url.strip()
        content = f"Source URL: {normalized_url}\n".encode("utf-8")
        content_hash = sha256(content).hexdigest()
        existing_source = self._find_existing_source(content_hash)
        if existing_source is not None:
            return SavedUpload(
                source=existing_source,
                saved_path=self.workspace_path / existing_source.path,
                is_duplicate=True,
            )

        source_id = f"src_{uuid.uuid4().hex}"
        filename = _safe_url_filename(normalized_url)
        relative_path = Path("evidence/files") / f"{source_id}_{filename}"
        saved_path = self.workspace_path / relative_path
        saved_path.parent.mkdir(parents=True, exist_ok=True)
        saved_path.write_bytes(content)

        source = EvidenceSource(
            id=source_id,
            type="url",
            label=label or _url_source_label(normalized_url),
            path=relative_path.as_posix(),
            originalFilename=filename,
            contentType="text/plain",
            sourceUrl=normalized_url,
            sizeBytes=len(content),
            contentHash=content_hash,
            extractionStatus="not_required",
            createdAt=datetime.now(timezone.utc),
        )
        self.evidence_repository.add_source(source)

        return SavedUpload(source=source, saved_path=saved_path)

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
        updated_source = source.model_copy(
            update={
                "content_hash": content_hash,
                "extracted_text_path": None,
                "extraction_status": "not_required",
                "size_bytes": len(content),
            }
        )
        self.evidence_repository.update_source(updated_source)

        return SavedUpload(
            source=updated_source,
            saved_path=saved_path,
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
    path_name = PureWindowsPath(filename).name.strip()
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", path_name)
    normalized = normalized.strip(".-")
    return normalized or "upload"


def _safe_url_filename(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc or "url"
    path = parsed.path.strip("/") or "source"
    return _safe_filename(f"{host}-{path}.txt")


def _url_source_label(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "linkedin.com" in host:
        return "LinkedIn"
    if "104.com.tw" in host:
        return "104 銀行"
    if "cake.me" in host or "cakeresume.com" in host:
        return "CakeResume"
    if "yourator.co" in host:
        return "Yourator"
    return host.removeprefix("www.") or "URL 來源"


def _hash_file(path: Path) -> str | None:
    if not path.is_file():
        return None

    return sha256(path.read_bytes()).hexdigest()

from __future__ import annotations

import json
from pathlib import Path

from app.schemas.evidence import EvidenceSource, EvidenceSourceCollection
from app.storage.atomic import atomic_write_json


class EvidenceRepository:
    def __init__(self, workspace_path: Path) -> None:
        self.workspace_path = workspace_path
        self.sources_path = workspace_path / "evidence/sources.json"

    def list_sources(self) -> EvidenceSourceCollection:
        if not self.sources_path.exists():
            return EvidenceSourceCollection()

        try:
            data = json.loads(self.sources_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return EvidenceSourceCollection()

        return EvidenceSourceCollection.model_validate(data)

    def add_source(self, source: EvidenceSource) -> EvidenceSourceCollection:
        collection = self.list_sources()
        updated = EvidenceSourceCollection(sources=[*collection.sources, source])
        atomic_write_json(
            self.sources_path,
            updated.model_dump(mode="json", by_alias=True),
        )
        return updated

    def find_by_content_hash(self, content_hash: str) -> EvidenceSource | None:
        for source in self.list_sources().sources:
            if source.content_hash == content_hash:
                return source
        return None

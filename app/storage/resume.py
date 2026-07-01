from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.schemas.resume import NormalizedResume
from app.storage.atomic import atomic_write_json


class ResumeRepository:
    def __init__(self, role_path: Path) -> None:
        self.role_path = role_path
        self.resume_path = role_path / "evidence/resume.json"

    def load(self) -> NormalizedResume:
        if not self.resume_path.is_file():
            return NormalizedResume()

        try:
            data = json.loads(self.resume_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return NormalizedResume()

        return NormalizedResume.model_validate(data)

    def save(self, resume: NormalizedResume) -> NormalizedResume:
        updated_resume = resume.model_copy(update={"updated_at": datetime.now(timezone.utc)})
        atomic_write_json(
            self.resume_path,
            updated_resume.model_dump(mode="json", by_alias=True),
        )
        return updated_resume


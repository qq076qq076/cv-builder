from __future__ import annotations

import json
from pathlib import Path

from app.schemas.job import TrackedJob, TrackedJobCollection
from app.storage.atomic import atomic_write_json


class JobRepository:
    def __init__(self, role_path: Path) -> None:
        self.role_path = role_path
        self.jobs_path = role_path / "jobs/jobs.json"

    def list_jobs(self) -> TrackedJobCollection:
        if not self.jobs_path.is_file():
            return TrackedJobCollection()

        try:
            data = json.loads(self.jobs_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return TrackedJobCollection()

        return TrackedJobCollection.model_validate(data)

    def add_job(self, job: TrackedJob) -> TrackedJobCollection:
        collection = self.list_jobs()
        updated = TrackedJobCollection(jobs=[job, *collection.jobs])
        atomic_write_json(self.jobs_path, updated.model_dump(mode="json", by_alias=True))
        return updated

    def get_job(self, job_id: str) -> TrackedJob | None:
        for job in self.list_jobs().jobs:
            if job.id == job_id:
                return job
        return None

    def remove_job(self, job_id: str) -> bool:
        collection = self.list_jobs()
        updated_jobs = [job for job in collection.jobs if job.id != job_id]
        if len(updated_jobs) == len(collection.jobs):
            return False
        atomic_write_json(
            self.jobs_path,
            TrackedJobCollection(jobs=updated_jobs).model_dump(mode="json", by_alias=True),
        )
        return True

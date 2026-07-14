from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.storage.atomic import atomic_write_json


_LOCKS: dict[Path, threading.Lock] = {}
_LOCKS_LOCK = threading.Lock()


@dataclass(frozen=True)
class GenerationTask:
    id: str
    job_id: str
    kind: str
    status: str
    output_path: str = ""
    pdf_path: str = ""
    error: str = ""
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> GenerationTask:
        return cls(
            id=str(data.get("id", "")),
            job_id=str(data.get("jobId", "")),
            kind=str(data.get("kind", "")),
            status=str(data.get("status", "")),
            output_path=str(data.get("outputPath", "")),
            pdf_path=str(data.get("pdfPath", "")),
            error=str(data.get("error", "")),
            created_at=str(data.get("createdAt", "")),
            updated_at=str(data.get("updatedAt", "")),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "jobId": self.job_id,
            "kind": self.kind,
            "status": self.status,
            "outputPath": self.output_path,
            "pdfPath": self.pdf_path,
            "error": self.error,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


class GenerationTaskRepository:
    def __init__(self, role_path: Path) -> None:
        self.tasks_path = role_path / "jobs/generation_tasks.json"

    def create_task(self, *, job_id: str, kind: str) -> GenerationTask:
        now = _now_iso()
        task = GenerationTask(
            id=f"gen_{uuid.uuid4().hex}",
            job_id=job_id,
            kind=kind,
            status="queued",
            created_at=now,
            updated_at=now,
        )
        with self._lock():
            tasks = self._read_tasks_unlocked()
            tasks = [
                existing
                for existing in tasks
                if not (
                    existing.job_id == job_id
                    and existing.kind == kind
                    and existing.status in {"queued", "running"}
                )
            ]
            tasks.insert(0, task)
            self._write_tasks_unlocked(tasks)
        return task

    def list_tasks(self) -> list[GenerationTask]:
        with self._lock():
            return self._read_tasks_unlocked()

    def remove_for_job(self, job_id: str) -> None:
        with self._lock():
            tasks = [task for task in self._read_tasks_unlocked() if task.job_id != job_id]
            self._write_tasks_unlocked(tasks)

    def recover_interrupted_tasks(self) -> int:
        """Mark tasks left active by a previous process as failed.

        The current worker uses daemon threads, so an application shutdown can
        leave queued/running tasks in the JSON file forever.  Recovery is
        intentionally explicit and idempotent so it is safe to run at startup.
        """
        with self._lock():
            tasks = self._read_tasks_unlocked()
            recovered = 0
            updated: list[GenerationTask] = []
            for task in tasks:
                if task.status not in {"queued", "running"}:
                    updated.append(task)
                    continue
                recovered += 1
                updated.append(
                    GenerationTask(
                        id=task.id,
                        job_id=task.job_id,
                        kind=task.kind,
                        status="failed",
                        output_path=task.output_path,
                        pdf_path=task.pdf_path,
                        error="應用程式在任務完成前中斷，請重新執行。",
                        created_at=task.created_at,
                        updated_at=_now_iso(),
                    )
                )
            if recovered:
                self._write_tasks_unlocked(updated)
            return recovered

    def latest_by_job(self) -> dict[str, dict[str, GenerationTask]]:
        latest: dict[str, dict[str, GenerationTask]] = {}
        for task in self.list_tasks():
            latest.setdefault(task.job_id, {}).setdefault(task.kind, task)
        return latest

    def get_task(self, task_id: str) -> GenerationTask | None:
        with self._lock():
            for task in self._read_tasks_unlocked():
                if task.id == task_id:
                    return task
        return None

    def cancel_active(self, *, job_id: str, kind: str) -> GenerationTask | None:
        with self._lock():
            tasks = self._read_tasks_unlocked()
            updated: list[GenerationTask] = []
            cancelled_task: GenerationTask | None = None
            for task in tasks:
                if (
                    cancelled_task is None
                    and task.job_id == job_id
                    and task.kind == kind
                    and task.status in {"queued", "running"}
                ):
                    cancelled_task = GenerationTask(
                        id=task.id,
                        job_id=task.job_id,
                        kind=task.kind,
                        status="cancelled",
                        output_path=task.output_path,
                        pdf_path=task.pdf_path,
                        error="",
                        created_at=task.created_at,
                        updated_at=_now_iso(),
                    )
                    updated.append(cancelled_task)
                    continue
                updated.append(task)
            self._write_tasks_unlocked(updated)
            return cancelled_task

    def mark_running(self, task_id: str) -> None:
        self._update_task(task_id, status="running")

    def mark_completed(
        self,
        task_id: str,
        *,
        output_path: str,
        pdf_path: str = "",
    ) -> None:
        self._update_task(
            task_id,
            status="completed",
            output_path=output_path,
            pdf_path=pdf_path,
            error="",
        )

    def mark_failed(self, task_id: str, *, error: str) -> None:
        self._update_task(task_id, status="failed", error=error)

    def _update_task(
        self,
        task_id: str,
        *,
        status: str,
        output_path: str | None = None,
        pdf_path: str | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock():
            tasks = self._read_tasks_unlocked()
            updated: list[GenerationTask] = []
            for task in tasks:
                if task.id != task_id:
                    updated.append(task)
                    continue
                if task.status == "cancelled":
                    updated.append(task)
                    continue
                updated.append(
                    GenerationTask(
                        id=task.id,
                        job_id=task.job_id,
                        kind=task.kind,
                        status=status,
                        output_path=task.output_path if output_path is None else output_path,
                        pdf_path=task.pdf_path if pdf_path is None else pdf_path,
                        error=task.error if error is None else error,
                        created_at=task.created_at,
                        updated_at=_now_iso(),
                    )
                )
            self._write_tasks_unlocked(updated)

    def _read_tasks_unlocked(self) -> list[GenerationTask]:
        if not self.tasks_path.is_file():
            return []
        try:
            data = json.loads(self.tasks_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        raw_tasks = data.get("tasks", []) if isinstance(data, dict) else []
        if not isinstance(raw_tasks, list):
            return []
        return [GenerationTask.from_dict(item) for item in raw_tasks if isinstance(item, dict)]

    def _write_tasks_unlocked(self, tasks: list[GenerationTask]) -> None:
        atomic_write_json(
            self.tasks_path,
            {
                "schemaVersion": 1,
                "tasks": [task.to_dict() for task in tasks[:100]],
            },
        )

    def _lock(self) -> threading.Lock:
        path = self.tasks_path.resolve()
        with _LOCKS_LOCK:
            if path not in _LOCKS:
                _LOCKS[path] = threading.Lock()
            return _LOCKS[path]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from app.schemas.job import TrackedJob
from app.schemas.resume import NormalizedResume
from app.storage.jobs import JobRepository


@dataclass(frozen=True)
class GeneratedJobOutput:
    path: str
    kind: str


class JobService:
    def __init__(self, role_path: Path) -> None:
        self.role_path = role_path
        self.repository = JobRepository(role_path)

    def list_jobs(self) -> list[TrackedJob]:
        return self.repository.list_jobs().jobs

    def create_job_from_url(self, url: str) -> TrackedJob:
        normalized_url = url.strip()
        title = _title_from_url(normalized_url)
        job = TrackedJob(
            id=f"job_{uuid.uuid4().hex}",
            title=title,
            company=_company_from_url(normalized_url),
            url=normalized_url,
            createdAt=datetime.now(timezone.utc),
        )
        self.repository.add_job(job)
        return job

    def generate_output(
        self,
        *,
        job_id: str,
        kind: str,
        resume: NormalizedResume,
    ) -> GeneratedJobOutput | None:
        job = self.repository.get_job(job_id)
        if job is None:
            return None

        safe_kind = "cover-letter" if kind == "cover_letter" else "resume"
        relative_path = Path("outputs") / f"{job.id}-{safe_kind}.md"
        output_path = self.role_path / relative_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            _build_generated_markdown(job=job, kind=kind, resume=resume),
            encoding="utf-8",
        )
        return GeneratedJobOutput(path=relative_path.as_posix(), kind=safe_kind)


def _title_from_url(url: str) -> str:
    parsed = urlparse(url)
    tail = Path(parsed.path).name
    cleaned = re.sub(r"[-_]+", " ", tail).strip()
    return cleaned.title() if cleaned else "未命名職缺"


def _company_from_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.replace("www.", "")
    return host or "Unknown"


def _build_generated_markdown(
    *,
    job: TrackedJob,
    kind: str,
    resume: NormalizedResume,
) -> str:
    title = "專用履歷草稿" if kind == "resume" else "推薦信草稿"
    skills = ", ".join(resume.skills[:12]) if resume.skills else "尚未解析技能"
    summary = resume.summary or "尚未解析摘要"
    return (
        f"# {title}\n\n"
        f"- 目標職缺：{job.title}\n"
        f"- 公司：{job.company}\n"
        f"- URL：{job.url}\n\n"
        f"## 候選人摘要\n\n{summary}\n\n"
        f"## 關鍵技能\n\n{skills}\n"
    )

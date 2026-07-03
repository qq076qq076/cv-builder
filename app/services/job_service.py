from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from app.ai.cover_letter_generator import CoverLetterGenerator
from app.ai.tailored_resume_generator import TailoredResumeGenerator
from app.schemas.job import TrackedJob
from app.schemas.resume import NormalizedResume
from app.storage.jobs import JobRepository
from app.services.url_fetcher import fetch_url_text


@dataclass(frozen=True)
class GeneratedJobOutput:
    path: str
    kind: str
    content: str = ""


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
        cover_letter_generator: CoverLetterGenerator | None = None,
        tailored_resume_generator: TailoredResumeGenerator | None = None,
    ) -> GeneratedJobOutput | None:
        job = self.repository.get_job(job_id)
        if job is None:
            return None

        safe_kind = "cover-letter" if kind == "cover_letter" else "resume"
        relative_path = Path("outputs") / f"{job.id}-{safe_kind}.md"
        output_path = self.role_path / relative_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        content = _build_generated_markdown(
            job=job,
            kind=kind,
            resume=resume,
            cover_letter_generator=cover_letter_generator,
            tailored_resume_generator=tailored_resume_generator,
        )
        output_path.write_text(
            content,
            encoding="utf-8",
        )
        return GeneratedJobOutput(path=relative_path.as_posix(), kind=safe_kind, content=content)

    def list_outputs_by_job(self) -> dict[str, dict[str, GeneratedJobOutput]]:
        outputs: dict[str, dict[str, GeneratedJobOutput]] = {}
        for job in self.list_jobs():
            for kind in ("resume", "cover-letter"):
                output = self.get_output(job_id=job.id, kind=kind)
                if output is not None:
                    outputs.setdefault(job.id, {})[kind] = output
        return outputs

    def get_output(self, *, job_id: str, kind: str) -> GeneratedJobOutput | None:
        safe_kind = "cover-letter" if kind in {"cover_letter", "cover-letter"} else "resume"
        relative_path = Path("outputs") / f"{job_id}-{safe_kind}.md"
        output_path = self.role_path / relative_path
        if not output_path.is_file():
            return None
        return GeneratedJobOutput(
            path=relative_path.as_posix(),
            kind=safe_kind,
            content=output_path.read_text(encoding="utf-8"),
        )

    def get_output_by_path(self, relative_path: str) -> GeneratedJobOutput | None:
        requested_path = Path(relative_path)
        if requested_path.is_absolute() or ".." in requested_path.parts:
            return None
        if requested_path.parts[:1] != ("outputs",):
            return None

        output_path = self.role_path / requested_path
        if not output_path.is_file():
            return None

        name = requested_path.name
        kind = "cover-letter" if name.endswith("-cover-letter.md") else "resume"
        return GeneratedJobOutput(
            path=requested_path.as_posix(),
            kind=kind,
            content=output_path.read_text(encoding="utf-8"),
        )


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
    cover_letter_generator: CoverLetterGenerator | None = None,
    tailored_resume_generator: TailoredResumeGenerator | None = None,
) -> str:
    if kind == "resume":
        if tailored_resume_generator is None:
            raise RuntimeError("缺少 OPENAI_API_KEY 或 GEMINI_API_KEY，無法生成專用履歷")
        return tailored_resume_generator.generate(
            resume=resume,
            job=job,
            job_page_text=_fetch_job_page_text(job.url),
        )

    if cover_letter_generator is None:
        raise RuntimeError("缺少 OPENAI_API_KEY 或 GEMINI_API_KEY，無法生成推薦信")

    return cover_letter_generator.generate(
        resume=resume,
        job=job,
        job_page_text=_fetch_job_page_text(job.url),
    )


def _fetch_job_page_text(url: str) -> str:
    result = fetch_url_text(url, timeout=10)
    if result.status != "completed":
        return ""
    return re.sub(r"\s+", " ", result.text).strip()[:8000]

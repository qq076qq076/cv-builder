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
from app.services.pdf_export_service import ResumePdfExporter
from app.services.url_fetcher import fetch_url_text
from app.storage.jobs import JobRepository


@dataclass(frozen=True)
class GeneratedJobOutput:
    path: str
    kind: str
    content: str = ""
    pdf_path: str | None = None
    job_id: str | None = None


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
        resume_pdf_exporter: ResumePdfExporter | None = None,
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
        pdf_path = None
        if safe_kind == "resume" and resume_pdf_exporter is not None:
            pdf_relative_path = Path("outputs") / f"{job.id}-{safe_kind}.pdf"
            resume_pdf_exporter.export(
                markdown=content,
                output_path=self.role_path / pdf_relative_path,
                job=job,
                resume=resume,
            )
            pdf_path = pdf_relative_path.as_posix()
        return GeneratedJobOutput(
            path=relative_path.as_posix(),
            kind=safe_kind,
            content=content,
            pdf_path=pdf_path,
            job_id=job.id,
        )

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
        pdf_path = self._pdf_path_for(job_id) if safe_kind == "resume" else None
        return GeneratedJobOutput(
            path=relative_path.as_posix(),
            kind=safe_kind,
            content=output_path.read_text(encoding="utf-8"),
            pdf_path=pdf_path.as_posix() if pdf_path is not None else None,
            job_id=job_id,
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
        job_id = _job_id_from_output_name(name, kind)
        pdf_path = self._pdf_path_for(job_id) if kind == "resume" and job_id else None
        return GeneratedJobOutput(
            path=requested_path.as_posix(),
            kind=kind,
            content=output_path.read_text(encoding="utf-8"),
            pdf_path=pdf_path.as_posix() if pdf_path is not None else None,
            job_id=job_id,
        )

    def get_resume_pdf_path(self, *, job_id: str) -> Path | None:
        if self.repository.get_job(job_id) is None:
            return None
        relative_path = self._pdf_path_for(job_id)
        if relative_path is None:
            return None
        return self.role_path / relative_path

    def _pdf_path_for(self, job_id: str) -> Path | None:
        relative_path = Path("outputs") / f"{job_id}-resume.pdf"
        if (self.role_path / relative_path).is_file():
            return relative_path
        return None


def _title_from_url(url: str) -> str:
    parsed = urlparse(url)
    tail = Path(parsed.path).name
    cleaned = re.sub(r"[-_]+", " ", tail).strip()
    return cleaned.title() if cleaned else "未命名職缺"


def _company_from_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.replace("www.", "")
    return host or "Unknown"


def _job_id_from_output_name(name: str, kind: str) -> str | None:
    suffix = "-cover-letter.md" if kind == "cover-letter" else "-resume.md"
    if not name.endswith(suffix):
        return None
    return name[: -len(suffix)]


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
    return _clean_job_page_text(result.text)


def _clean_job_page_text(text: str, *, max_chars: int = 6000) -> str:
    lines = _clean_job_page_lines(text)
    lines = _slice_job_relevant_lines(lines)
    return re.sub(r"\s+", " ", " ".join(lines)).strip()[:max_chars]


def _clean_job_page_lines(text: str) -> list[str]:
    seen: set[str] = set()
    cleaned_lines: list[str] = []
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        if _is_job_page_noise_line(line):
            continue
        normalized = line.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        cleaned_lines.append(line)
    return cleaned_lines


def _slice_job_relevant_lines(lines: list[str]) -> list[str]:
    if not lines:
        return []

    start_index = 0
    for index, line in enumerate(lines):
        if _is_job_content_start(line):
            start_index = max(0, index - 3)
            break

    end_index = len(lines)
    for index in range(start_index + 1, len(lines)):
        if _is_job_content_end(lines[index]):
            end_index = index
            break

    return lines[start_index:end_index]


def _is_job_content_start(line: str) -> bool:
    return bool(
        re.search(
            r"職務內容|工作內容|職缺描述|工作說明|職責|應徵條件|工作條件|資格條件|"
            r"job description|about the job|responsibilit(?:y|ies)|requirements?|"
            r"qualifications?|what you(?:'|’)ll do|what you will do",
            line,
            flags=re.IGNORECASE,
        )
    )


def _is_job_content_end(line: str) -> bool:
    return bool(
        re.search(
            r"相似職缺|推薦職缺|更多職缺|其他工作|看更多|應徵紀錄|公司福利|"
            r"similar jobs|recommended jobs|more jobs|other jobs|related jobs|"
            r"people also viewed|share this job|job alert|apply for another",
            line,
            flags=re.IGNORECASE,
        )
    )


def _is_job_page_noise_line(line: str) -> bool:
    if len(line) <= 1:
        return True
    if re.fullmatch(r"[\W_]+", line):
        return True
    return bool(
        re.search(
            r"登入|註冊|會員中心|收藏|分享|複製連結|檢舉|回報|隱私權|服務條款|"
            r"cookie|cookies|privacy policy|terms of service|sign in|log in|register|"
            r"create account|save job|share|copy link|report job|follow company|"
            r"download app|app store|google play|facebook|instagram|linkedin|"
            r"©|copyright|all rights reserved",
            line,
            flags=re.IGNORECASE,
        )
    )

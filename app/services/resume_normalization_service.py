from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.ai.resume_parser import GeminiResumeParser, OpenAIResumeParser, ResumeParser
from app.schemas.resume import NormalizedResume
from app.storage.evidence import EvidenceRepository
from app.storage.resume import ResumeRepository


@dataclass(frozen=True)
class ResumeNormalizationResult:
    status: str
    resume: NormalizedResume | None = None
    message: str = ""


class ResumeNormalizationService:
    def __init__(
        self,
        *,
        role_path: Path,
        api_key: str | None,
        model: str,
        gemini_api_key: str | None = None,
        gemini_model: str = "gemini-3.5-flash",
        parser: ResumeParser | None = None,
    ) -> None:
        self.role_path = role_path
        self.evidence_repository = EvidenceRepository(role_path)
        self.resume_repository = ResumeRepository(role_path)
        self.api_key = api_key
        self.model = model
        self.gemini_api_key = gemini_api_key
        self.gemini_model = gemini_model
        self.parser = parser

    def normalize_source(self, source_id: str) -> ResumeNormalizationResult:
        source = self.evidence_repository.get_source(source_id)
        if source is None:
            return ResumeNormalizationResult(status="not_found", message="找不到來源")
        if not self.api_key and not self.gemini_api_key and self.parser is None:
            return ResumeNormalizationResult(
                status="missing_api_key",
                message="缺少 OPENAI_API_KEY 或 GEMINI_API_KEY",
            )

        source_path = self.role_path / source.path
        if not source_path.is_file():
            return ResumeNormalizationResult(status="no_text", message="找不到來源檔案")

        parser = self.parser or self._build_parser()
        try:
            content = source_path.read_bytes()
            resume = _parse_source_file(
                parser=parser,
                filename=source.original_filename,
                content_type=source.content_type,
                content=content,
                source_id=source.id,
            )
            _validate_resume_detail(resume)
        except Exception as exc:
            return ResumeNormalizationResult(
                status="failed",
                message=f"履歷解析失敗：{exc}",
            )

        saved_resume = self.resume_repository.save(resume)

        return ResumeNormalizationResult(status="completed", resume=saved_resume)

    def _build_parser(self) -> ResumeParser:
        if self.api_key:
            return OpenAIResumeParser(
                api_key=self.api_key,
                model=self.model,
                log_path=self.role_path / "logs/ai-parser.jsonl",
            )
        return GeminiResumeParser(
            api_key=self.gemini_api_key or "",
            model=self.gemini_model,
            log_path=self.role_path / "logs/ai-parser.jsonl",
        )


def _parse_source_file(
    *,
    parser: ResumeParser,
    filename: str,
    content_type: str | None,
    content: bytes,
    source_id: str,
) -> NormalizedResume:
    parse_file = getattr(parser, "parse_file", None)
    if callable(parse_file):
        return parse_file(
            filename=filename,
            content_type=content_type,
            content=content,
            source_id=source_id,
        )

    return parser.parse(
        extracted_text=content.decode("utf-8", errors="ignore"),
        source_id=source_id,
    )


def _validate_resume_detail(resume: NormalizedResume) -> None:
    has_identity = bool(resume.name.strip() or resume.title.strip())
    has_contact = bool(
        resume.contact.email.strip()
        or resume.contact.phone.strip()
        or resume.contact.location.strip()
        or resume.contact.links
    )
    has_detail = any(
        [
            resume.summary.strip(),
            resume.autobiography.strip(),
            has_contact,
            resume.skills,
            resume.experiences,
            resume.projects,
            resume.education,
            resume.certificates,
            resume.languages,
        ]
    )

    if not has_identity or not has_detail:
        raise ValueError(
            "AI result is too sparse; expected identity plus skills, experience, "
            "projects, education, contact, summary, certificates, or languages"
        )

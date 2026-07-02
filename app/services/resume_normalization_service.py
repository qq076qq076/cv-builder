from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from app.ai.resume_parser import GeminiResumeParser, OpenAIResumeParser, ResumeParser
from app.importers.pdf import can_extract_pdf, extract_text_from_pdf_bytes
from app.importers.text import can_extract_text, extract_text_from_bytes
from app.schemas.resume import NormalizedResume
from app.storage.evidence import EvidenceRepository
from app.storage.resume import ResumeRepository
from app.services.url_fetcher import UrlFetchResult, fetch_url_text, render_fetched_url_evidence


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
        url_fetcher=fetch_url_text,
    ) -> None:
        self.role_path = role_path
        self.evidence_repository = EvidenceRepository(role_path)
        self.resume_repository = ResumeRepository(role_path)
        self.api_key = api_key
        self.model = model
        self.gemini_api_key = gemini_api_key
        self.gemini_model = gemini_model
        self.parser = parser
        self.url_fetcher = url_fetcher

    def normalize_source(self, source_id: str) -> ResumeNormalizationResult:
        source = self.evidence_repository.get_source(source_id)
        if source is None:
            return ResumeNormalizationResult(status="not_found", message="找不到來源")
        if not self.api_key and not self.gemini_api_key and self.parser is None:
            return ResumeNormalizationResult(
                status="missing_api_key",
                message="缺少 OPENAI_API_KEY 或 GEMINI_API_KEY",
            )

        source = self._refresh_url_source(source)
        source_path = self.role_path / source.path
        if not source_path.is_file():
            return ResumeNormalizationResult(status="no_text", message="找不到來源檔案")

        parser = self.parser or self._build_parser()
        try:
            content = source_path.read_bytes()
            extracted_text = _extract_supplemental_text(
                filename=source.original_filename,
                content_type=source.content_type,
                content=content,
            )
            resume = _parse_source_file(
                parser=parser,
                filename=source.original_filename,
                content_type=source.content_type,
                content=content,
                extracted_text=extracted_text,
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

    def normalize_sources(self, source_ids: list[str]) -> ResumeNormalizationResult:
        sources = [
            source
            for source_id in source_ids
            if (source := self.evidence_repository.get_source(source_id)) is not None
        ]
        if not sources:
            return ResumeNormalizationResult(status="not_found", message="目前沒有可解析的來源")
        if not self.api_key and not self.gemini_api_key and self.parser is None:
            return ResumeNormalizationResult(
                status="missing_api_key",
                message="缺少 OPENAI_API_KEY 或 GEMINI_API_KEY",
            )

        source_sections = []
        for source in sources:
            source = self._refresh_url_source(source)
            source_path = self.role_path / source.path
            if not source_path.is_file():
                continue

            content = source_path.read_bytes()
            extracted_text = _extract_supplemental_text(
                filename=source.original_filename,
                content_type=source.content_type,
                content=content,
            )
            source_text = extracted_text or content.decode("utf-8", errors="ignore").strip()
            if not source_text:
                source_text = f"[無法抽取文字；來源檔案：{source.original_filename}]"

            source_sections.append(
                "\n".join(
                    [
                        f"## Source ID: {source.id}",
                        f"Label: {source.label}",
                        f"Type: {source.type}",
                        "",
                        source_text,
                    ]
                )
            )

        if not source_sections:
            return ResumeNormalizationResult(status="no_text", message="找不到來源檔案")

        combined_source_id = ",".join(source.id for source in sources)
        combined_text = (
            "請整合以下多個來源，去除重複資訊，保留所有可驗證事實，"
            "輸出一份一致的結構化履歷資料。\n\n"
            + "\n\n---\n\n".join(source_sections)
        )

        parser = self.parser or self._build_parser()
        try:
            resume = parser.parse(extracted_text=combined_text, source_id=combined_source_id)
            resume = resume.model_copy(update={"source_ids": [source.id for source in sources]})
            _validate_resume_detail(resume)
        except Exception as exc:
            return ResumeNormalizationResult(
                status="failed",
                message=f"履歷解析失敗：{exc}",
            )

        saved_resume = self.resume_repository.save(resume)

        return ResumeNormalizationResult(status="completed", resume=saved_resume)

    def _refresh_url_source(self, source):
        if source.type != "url" or not source.source_url:
            return source

        result = self.url_fetcher(source.source_url)
        if not isinstance(result, UrlFetchResult):
            result = UrlFetchResult(
                url=source.source_url,
                status="failed",
                message="URL fetcher did not return UrlFetchResult",
            )
        content = render_fetched_url_evidence(result).encode("utf-8")
        source_path = self.role_path / source.path
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(content)

        updated_source = source.model_copy(
            update={
                "size_bytes": len(content),
                "content_hash": sha256(content).hexdigest(),
                "extraction_status": result.status,
            }
        )
        self.evidence_repository.update_source(updated_source)
        return updated_source

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
    extracted_text: str | None,
    source_id: str,
) -> NormalizedResume:
    parse_file = getattr(parser, "parse_file", None)
    if callable(parse_file):
        return parse_file(
            filename=filename,
            content_type=content_type,
            content=content,
            extracted_text=extracted_text,
            source_id=source_id,
        )

    return parser.parse(
        extracted_text=extracted_text or content.decode("utf-8", errors="ignore"),
        source_id=source_id,
    )


def _extract_supplemental_text(
    *,
    filename: str,
    content_type: str | None,
    content: bytes,
) -> str | None:
    try:
        if can_extract_text(filename):
            return extract_text_from_bytes(content)
        if can_extract_pdf(filename, content_type):
            return extract_text_from_pdf_bytes(content)
    except Exception:
        return None

    return None


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

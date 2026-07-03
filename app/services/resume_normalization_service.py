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
    error_stage: str = ""


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

        source, fetch_result = self._refresh_url_source(source)
        if fetch_result is not None and fetch_result.status != "completed":
            return ResumeNormalizationResult(
                status="fetch_failed",
                message=_url_fetch_failure_message(fetch_result),
                error_stage="url_fetch",
            )
        source_path = self.role_path / source.path
        if not source_path.is_file():
            return ResumeNormalizationResult(
                status="no_text",
                message="來源檔案階段失敗：找不到來源檔案",
                error_stage="source_file",
            )

        parser = self.parser or self._build_parser()
        try:
            content = source_path.read_bytes()
        except OSError as exc:
            return ResumeNormalizationResult(
                status="failed",
                message=f"來源檔案讀取階段失敗：{exc}",
                error_stage="source_file",
            )

        try:
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
                message=_ai_parse_failure_message(exc),
                error_stage="ai_parse",
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
        fetch_failures = []
        for source in sources:
            source, fetch_result = self._refresh_url_source(source)
            if fetch_result is not None and fetch_result.status != "completed":
                fetch_failures.append(_url_fetch_failure_message(fetch_result))
                continue

            source_path = self.role_path / source.path
            if not source_path.is_file():
                continue

            try:
                content = source_path.read_bytes()
            except OSError:
                continue

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
            if fetch_failures:
                return ResumeNormalizationResult(
                    status="fetch_failed",
                    message="；".join(fetch_failures),
                    error_stage="url_fetch",
                )
            return ResumeNormalizationResult(
                status="no_text",
                message="來源檔案階段失敗：找不到可解析的來源檔案",
                error_stage="source_file",
            )

        combined_source_id = ",".join(source.id for source in sources)
        combined_text = (
            "請整合以下多個來源，去除重複資訊，保留所有可驗證事實，"
            "輸出一份一致的結構化履歷資料。\n\n" + "\n\n---\n\n".join(source_sections)
        )

        parser = self.parser or self._build_parser()
        try:
            resume = parser.parse(extracted_text=combined_text, source_id=combined_source_id)
            resume = resume.model_copy(update={"source_ids": [source.id for source in sources]})
            _validate_resume_detail(resume)
        except Exception as exc:
            return ResumeNormalizationResult(
                status="failed",
                message=_ai_parse_failure_message(exc),
                error_stage="ai_parse",
            )

        saved_resume = self.resume_repository.save(resume)

        return ResumeNormalizationResult(status="completed", resume=saved_resume)

    def _refresh_url_source(self, source):
        if source.type != "url" or not source.source_url:
            return source, None

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
        return updated_source, result

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


def _url_fetch_failure_message(result: UrlFetchResult) -> str:
    detail = result.message or "未取得頁面內容"
    return f"URL 抓取階段失敗：{result.url}：{detail}"


def _ai_parse_failure_message(exc: Exception) -> str:
    detail = str(exc) or exc.__class__.__name__
    if _looks_like_timeout(exc):
        return f"AI 解析階段逾時：{detail}"
    return f"AI 解析階段失敗：{detail}"


def _looks_like_timeout(exc: Exception) -> bool:
    text = f"{exc.__class__.__name__}: {exc}".lower()
    return "timeout" in text or "timed out" in text or "逾時" in text

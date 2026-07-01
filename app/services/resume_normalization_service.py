from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.ai.resume_parser import OpenAIResumeParser
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
        parser: OpenAIResumeParser | None = None,
    ) -> None:
        self.role_path = role_path
        self.evidence_repository = EvidenceRepository(role_path)
        self.resume_repository = ResumeRepository(role_path)
        self.api_key = api_key
        self.model = model
        self.parser = parser

    def normalize_source(self, source_id: str) -> ResumeNormalizationResult:
        source = self.evidence_repository.get_source(source_id)
        if source is None:
            return ResumeNormalizationResult(status="not_found", message="找不到來源")
        if source.extracted_text_path is None:
            return ResumeNormalizationResult(status="no_text", message="來源尚未完成文字抽取")
        if not self.api_key and self.parser is None:
            return ResumeNormalizationResult(status="missing_api_key", message="缺少 OPENAI_API_KEY")

        extracted_path = self.role_path / source.extracted_text_path
        if not extracted_path.is_file():
            return ResumeNormalizationResult(status="no_text", message="找不到抽取文字檔")

        extracted_text = extracted_path.read_text(encoding="utf-8")
        parser = self.parser or OpenAIResumeParser(api_key=self.api_key or "", model=self.model)
        try:
            resume = parser.parse(extracted_text=extracted_text, source_id=source.id)
        except Exception as exc:
            return ResumeNormalizationResult(
                status="failed",
                message=f"履歷解析失敗：{exc}",
            )

        saved_resume = self.resume_repository.save(resume)

        return ResumeNormalizationResult(status="completed", resume=saved_resume)

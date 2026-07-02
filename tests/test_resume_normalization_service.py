import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app.schemas.evidence import EvidenceSource
from app.schemas.resume import NormalizedResume
from app.services.resume_normalization_service import ResumeNormalizationService
from app.storage.evidence import EvidenceRepository
from app.storage.resume import ResumeRepository


class FakeParser:
    def parse(self, *, extracted_text: str, source_id: str) -> NormalizedResume:
        return NormalizedResume(
            sourceIds=[source_id],
            name="Walker Lin",
            skills=["Python", "FastAPI"],
            summary=extracted_text[:20],
        )


class FakeFileParser:
    def parse_file(
        self,
        *,
        filename: str,
        content_type: str | None,
        content: bytes,
        source_id: str,
    ) -> NormalizedResume:
        return NormalizedResume(
            sourceIds=[source_id],
            name="Walker Lin",
            skills=["Python", "FastAPI"],
            summary=f"{filename}:{content_type}:{content.decode('utf-8')}",
        )


class FakeProviderParser:
    calls: list[tuple[str, str]] = []

    def __init__(self, *, api_key: str, model: str, log_path: Path | None = None) -> None:
        self.api_key = api_key
        self.model = model
        self.log_path = log_path

    def parse(self, *, extracted_text: str, source_id: str) -> NormalizedResume:
        self.calls.append((self.api_key, self.model))
        return NormalizedResume(
            sourceIds=[source_id],
            name=self.model,
            skills=["Python"],
        )


class SparseFileParser:
    def parse_file(
        self,
        *,
        filename: str,
        content_type: str | None,
        content: bytes,
        source_id: str,
    ) -> NormalizedResume:
        return NormalizedResume(sourceIds=[source_id], title="Senior Frontend Engineer")


class ResumeNormalizationServiceTest(unittest.TestCase):
    def test_normalize_source_saves_resume_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = self._role_with_source_file(Path(tmpdir))

            result = ResumeNormalizationService(
                role_path=role_path,
                api_key=None,
                model="test-model",
                parser=FakeFileParser(),
            ).normalize_source("src_1")

            self.assertEqual(result.status, "completed")
            loaded = ResumeRepository(role_path).load()
            self.assertEqual(loaded.name, "Walker Lin")
            self.assertEqual(loaded.skills, ["Python", "FastAPI"])
            self.assertIn("resume.txt:text/plain", loaded.summary)

    def test_sparse_ai_result_fails_without_writing_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = self._role_with_source_file(Path(tmpdir))

            result = ResumeNormalizationService(
                role_path=role_path,
                api_key=None,
                model="test-model",
                parser=SparseFileParser(),
            ).normalize_source("src_1")

            self.assertEqual(result.status, "failed")
            self.assertIn("too sparse", result.message)
            self.assertFalse((role_path / "evidence/resume.json").exists())

    def test_missing_api_key_returns_error_without_parser(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = self._role_with_source_file(Path(tmpdir))

            result = ResumeNormalizationService(
                role_path=role_path,
                api_key=None,
                model="test-model",
            ).normalize_source("src_1")

            self.assertEqual(result.status, "missing_api_key")
            self.assertEqual(result.message, "缺少 OPENAI_API_KEY 或 GEMINI_API_KEY")

    def test_uses_openai_when_openai_key_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = self._role_with_source_file(Path(tmpdir))
            FakeProviderParser.calls = []

            with patch(
                "app.services.resume_normalization_service.OpenAIResumeParser",
                FakeProviderParser,
            ):
                result = ResumeNormalizationService(
                    role_path=role_path,
                    api_key="openai-key",
                    model="openai-model",
                    gemini_api_key="gemini-key",
                    gemini_model="gemini-model",
                ).normalize_source("src_1")

            self.assertEqual(result.status, "completed")
            self.assertEqual(FakeProviderParser.calls, [("openai-key", "openai-model")])

    def test_uses_gemini_when_only_gemini_key_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = self._role_with_source_file(Path(tmpdir))
            FakeProviderParser.calls = []

            with patch(
                "app.services.resume_normalization_service.GeminiResumeParser",
                FakeProviderParser,
            ):
                result = ResumeNormalizationService(
                    role_path=role_path,
                    api_key="",
                    model="openai-model",
                    gemini_api_key="gemini-key",
                    gemini_model="gemini-model",
                ).normalize_source("src_1")

            self.assertEqual(result.status, "completed")
            self.assertEqual(FakeProviderParser.calls, [("gemini-key", "gemini-model")])

    def _role_with_source_file(
        self,
        root: Path,
        content: str = "Senior Python Engineer",
    ) -> Path:
        role_path = root / "workspace/walker"
        source_path = role_path / "evidence/files/src_1_resume.txt"
        source_path.parent.mkdir(parents=True)
        source_path.write_text(content, encoding="utf-8")
        EvidenceRepository(role_path).add_source(
            EvidenceSource(
                id="src_1",
                label="resume.txt",
                path="evidence/files/src_1_resume.txt",
                originalFilename="resume.txt",
                contentType="text/plain",
                sizeBytes=22,
                extractionStatus="not_required",
                createdAt=datetime(2026, 7, 1, tzinfo=timezone.utc),
            )
        )
        return role_path


if __name__ == "__main__":
    unittest.main()

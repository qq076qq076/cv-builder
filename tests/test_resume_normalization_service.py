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


class FakeProviderParser:
    calls: list[tuple[str, str]] = []

    def __init__(self, *, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    def parse(self, *, extracted_text: str, source_id: str) -> NormalizedResume:
        self.calls.append((self.api_key, self.model))
        return NormalizedResume(sourceIds=[source_id], name=self.model)


class IncompleteParser:
    def parse(self, *, extracted_text: str, source_id: str) -> NormalizedResume:
        return NormalizedResume(sourceIds=[source_id], name="Walker Lin")


class ResumeNormalizationServiceTest(unittest.TestCase):
    def test_normalize_source_saves_resume_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = Path(tmpdir) / "workspace/walker"
            extracted_path = role_path / "evidence/extracted/src_1.txt"
            extracted_path.parent.mkdir(parents=True)
            extracted_path.write_text("Senior Python Engineer", encoding="utf-8")
            EvidenceRepository(role_path).add_source(
                EvidenceSource(
                    id="src_1",
                    label="resume.txt",
                    path="evidence/files/src_1_resume.txt",
                    originalFilename="resume.txt",
                    contentType="text/plain",
                    sizeBytes=22,
                    extractedTextPath="evidence/extracted/src_1.txt",
                    extractionStatus="completed",
                    createdAt=datetime(2026, 7, 1, tzinfo=timezone.utc),
                )
            )

            result = ResumeNormalizationService(
                role_path=role_path,
                api_key=None,
                model="test-model",
                parser=FakeParser(),
            ).normalize_source("src_1")

            self.assertEqual(result.status, "completed")
            loaded = ResumeRepository(role_path).load()
            self.assertEqual(loaded.name, "Walker Lin")
            self.assertEqual(loaded.skills, ["Python", "FastAPI"])

    def test_missing_api_key_returns_error_without_parser(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = self._role_with_extracted_source(Path(tmpdir))

            result = ResumeNormalizationService(
                role_path=role_path,
                api_key=None,
                model="test-model",
            ).normalize_source("src_1")

            self.assertEqual(result.status, "missing_api_key")
            self.assertEqual(result.message, "缺少 OPENAI_API_KEY 或 GEMINI_API_KEY")

    def test_uses_openai_when_openai_key_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = self._role_with_extracted_source(Path(tmpdir))
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
            role_path = self._role_with_extracted_source(Path(tmpdir))
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

    def test_incomplete_ai_result_fails_without_writing_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = self._role_with_extracted_source(
                Path(tmpdir),
                extracted_text="SKILLS\nAngular\nEXPERIENCE\nEngineer\nPROJECTS\nWEBA",
            )

            result = ResumeNormalizationService(
                role_path=role_path,
                api_key=None,
                model="test-model",
                parser=IncompleteParser(),
            ).normalize_source("src_1")

            self.assertEqual(result.status, "failed")
            self.assertIn("missing expected sections", result.message)
            self.assertFalse((role_path / "evidence/resume.json").exists())

    def _role_with_extracted_source(
        self,
        root: Path,
        extracted_text: str = "Senior Python Engineer",
    ) -> Path:
        role_path = root / "workspace/walker"
        extracted_path = role_path / "evidence/extracted/src_1.txt"
        extracted_path.parent.mkdir(parents=True)
        extracted_path.write_text(extracted_text, encoding="utf-8")
        EvidenceRepository(role_path).add_source(
            EvidenceSource(
                id="src_1",
                label="resume.txt",
                path="evidence/files/src_1_resume.txt",
                originalFilename="resume.txt",
                contentType="text/plain",
                sizeBytes=22,
                extractedTextPath="evidence/extracted/src_1.txt",
                extractionStatus="completed",
                createdAt=datetime(2026, 7, 1, tzinfo=timezone.utc),
            )
        )
        return role_path


if __name__ == "__main__":
    unittest.main()

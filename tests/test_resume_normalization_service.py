import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

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
            role_path = Path(tmpdir) / "workspace/walker"

            result = ResumeNormalizationService(
                role_path=role_path,
                api_key=None,
                model="test-model",
            ).normalize_source("src_1")

            self.assertEqual(result.status, "not_found")


if __name__ == "__main__":
    unittest.main()


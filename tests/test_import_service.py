import tempfile
import unittest
from hashlib import sha256
from datetime import datetime, timezone
from pathlib import Path

from app.schemas.evidence import EvidenceSource
from app.services.import_service import ImportService
from app.storage.evidence import EvidenceRepository
from tests.test_pdf_importer import SIMPLE_TEXT_PDF


class ImportServiceTest(unittest.TestCase):
    def test_save_uploaded_file_writes_file_and_evidence_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            service = ImportService(workspace)

            saved_upload = service.save_uploaded_file(
                filename="../My Resume.txt",
                content_type="text/plain",
                content=b"hello",
            )

            self.assertTrue(saved_upload.saved_path.is_file())
            self.assertEqual(saved_upload.saved_path.read_bytes(), b"hello")
            self.assertTrue(saved_upload.source.path.startswith("evidence/files/src_"))
            self.assertTrue(saved_upload.source.path.endswith("_My-Resume.txt"))
            self.assertEqual(saved_upload.source.extraction_status, "not_required")
            self.assertIsNone(saved_upload.source.extracted_text_path)

            sources = EvidenceRepository(workspace).list_sources()
            self.assertEqual(len(sources.sources), 1)
            self.assertEqual(sources.sources[0].id, saved_upload.source.id)
            self.assertEqual(sources.sources[0].size_bytes, 5)
            self.assertEqual(sources.sources[0].content_hash, sha256(b"hello").hexdigest())
            self.assertEqual(sources.sources[0].extraction_status, "not_required")

    def test_save_pdf_does_not_extract_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            service = ImportService(workspace)

            saved_upload = service.save_uploaded_file(
                filename="resume.pdf",
                content_type="application/pdf",
                content=SIMPLE_TEXT_PDF,
            )

            self.assertEqual(saved_upload.source.extraction_status, "not_required")
            self.assertIsNone(saved_upload.source.extracted_text_path)
            self.assertFalse((workspace / "evidence/extracted").exists())

    def test_duplicate_content_reuses_existing_source_without_extracting(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            service = ImportService(workspace)

            first_upload = service.save_uploaded_file(
                filename="resume.txt",
                content_type="text/plain",
                content=b"same content",
            )
            second_upload = service.save_uploaded_file(
                filename="copy.txt",
                content_type="text/plain",
                content=b"same content",
            )

            self.assertFalse(first_upload.is_duplicate)
            self.assertTrue(second_upload.is_duplicate)
            self.assertEqual(second_upload.source.id, first_upload.source.id)
            self.assertEqual(len(EvidenceRepository(workspace).list_sources().sources), 1)
            self.assertEqual(len(list((workspace / "evidence/files").iterdir())), 1)
            self.assertFalse((workspace / "evidence/extracted").exists())

    def test_duplicate_content_matches_existing_source_without_content_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            existing_path = workspace / "evidence/files/src_old_resume.txt"
            existing_path.parent.mkdir(parents=True)
            existing_path.write_bytes(b"legacy content")
            EvidenceRepository(workspace).add_source(
                EvidenceSource(
                    id="src_old",
                    label="old resume",
                    path="evidence/files/src_old_resume.txt",
                    originalFilename="old.txt",
                    contentType="text/plain",
                    sizeBytes=len(b"legacy content"),
                    createdAt=datetime(2026, 7, 1, tzinfo=timezone.utc),
                )
            )

            saved_upload = ImportService(workspace).save_uploaded_file(
                filename="new.txt",
                content_type="text/plain",
                content=b"legacy content",
            )

            self.assertTrue(saved_upload.is_duplicate)
            self.assertEqual(saved_upload.source.id, "src_old")
            self.assertEqual(len(EvidenceRepository(workspace).list_sources().sources), 1)

    def test_invalid_pdf_is_saved_without_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            service = ImportService(workspace)

            saved_upload = service.save_uploaded_file(
                filename="resume.pdf",
                content_type="application/pdf",
                content=b"%PDF",
            )

            self.assertTrue(saved_upload.saved_path.is_file())
            self.assertEqual(saved_upload.source.extraction_status, "not_required")
            self.assertIsNone(saved_upload.source.extracted_text_path)

    def test_reprocess_source_updates_hash_without_extracting(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            existing_path = workspace / "evidence/files/src_old_resume.pdf"
            existing_path.parent.mkdir(parents=True)
            existing_path.write_bytes(SIMPLE_TEXT_PDF)
            EvidenceRepository(workspace).add_source(
                EvidenceSource(
                    id="src_old",
                    label="old resume",
                    path="evidence/files/src_old_resume.pdf",
                    originalFilename="old.pdf",
                    contentType="application/pdf",
                    sizeBytes=len(SIMPLE_TEXT_PDF),
                    createdAt=datetime(2026, 7, 1, tzinfo=timezone.utc),
                )
            )

            saved_upload = ImportService(workspace).reprocess_source("src_old")

            self.assertIsNotNone(saved_upload)
            self.assertEqual(saved_upload.source.extraction_status, "not_required")
            self.assertIsNotNone(saved_upload.source.content_hash)
            self.assertIsNone(saved_upload.source.extracted_text_path)

            updated_source = EvidenceRepository(workspace).get_source("src_old")
            self.assertEqual(updated_source.extraction_status, "not_required")
            self.assertIsNotNone(updated_source.content_hash)

    def test_reprocess_missing_source_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"

            self.assertIsNone(ImportService(workspace).reprocess_source("missing"))


if __name__ == "__main__":
    unittest.main()

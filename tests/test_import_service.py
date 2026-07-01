import tempfile
import unittest
from pathlib import Path

from app.services.import_service import ImportService
from app.storage.evidence import EvidenceRepository


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
            self.assertEqual(saved_upload.source.extraction_status, "completed")
            self.assertEqual(saved_upload.extracted_text, "hello")
            self.assertIsNotNone(saved_upload.source.extracted_text_path)
            self.assertTrue((workspace / saved_upload.source.extracted_text_path).is_file())
            self.assertEqual(
                (workspace / saved_upload.source.extracted_text_path).read_text(encoding="utf-8"),
                "hello",
            )

            sources = EvidenceRepository(workspace).list_sources()
            self.assertEqual(len(sources.sources), 1)
            self.assertEqual(sources.sources[0].id, saved_upload.source.id)
            self.assertEqual(sources.sources[0].size_bytes, 5)
            self.assertEqual(sources.sources[0].extraction_status, "completed")

    def test_save_unsupported_file_does_not_create_extracted_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            service = ImportService(workspace)

            saved_upload = service.save_uploaded_file(
                filename="resume.pdf",
                content_type="application/pdf",
                content=b"%PDF",
            )

            self.assertEqual(saved_upload.source.extraction_status, "not_supported")
            self.assertIsNone(saved_upload.source.extracted_text_path)
            self.assertIsNone(saved_upload.extracted_text)


if __name__ == "__main__":
    unittest.main()

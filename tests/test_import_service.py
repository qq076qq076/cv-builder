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

            sources = EvidenceRepository(workspace).list_sources()
            self.assertEqual(len(sources.sources), 1)
            self.assertEqual(sources.sources[0].id, saved_upload.source.id)
            self.assertEqual(sources.sources[0].size_bytes, 5)


if __name__ == "__main__":
    unittest.main()


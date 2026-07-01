import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.schemas.evidence import EvidenceSource
from app.storage.evidence import EvidenceRepository


class EvidenceRepositoryTest(unittest.TestCase):
    def test_add_source_creates_sources_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            repository = EvidenceRepository(workspace)
            source = EvidenceSource(
                id="src_test",
                label="resume.txt",
                path="evidence/files/src_test_resume.txt",
                originalFilename="resume.txt",
                contentType="text/plain",
                sizeBytes=5,
                contentHash="abc123",
                createdAt=datetime(2026, 7, 1, tzinfo=timezone.utc),
            )

            collection = repository.add_source(source)

            self.assertEqual(len(collection.sources), 1)
            self.assertTrue((workspace / "evidence/sources.json").is_file())

            loaded = repository.list_sources()
            self.assertEqual(loaded.schema_version, 1)
            self.assertEqual(loaded.sources[0].id, "src_test")
            self.assertEqual(loaded.sources[0].path, "evidence/files/src_test_resume.txt")
            self.assertEqual(repository.find_by_content_hash("abc123").id, "src_test")
            self.assertIsNone(repository.find_by_content_hash("missing"))


if __name__ == "__main__":
    unittest.main()

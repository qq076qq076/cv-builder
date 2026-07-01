import tempfile
import unittest
from pathlib import Path

from app.schemas.resume import NormalizedResume, ResumeExperience
from app.storage.resume import ResumeRepository


class ResumeRepositoryTest(unittest.TestCase):
    def test_save_and_load_normalized_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = Path(tmpdir) / "workspace/walker"
            repository = ResumeRepository(role_path)

            repository.save(
                NormalizedResume(
                    sourceIds=["src_1"],
                    name="Walker Lin",
                    skills=["Python"],
                    experiences=[ResumeExperience(company="Acme", title="Engineer")],
                )
            )

            loaded = repository.load()
            self.assertEqual(loaded.name, "Walker Lin")
            self.assertEqual(loaded.source_ids, ["src_1"])
            self.assertEqual(loaded.experiences[0].company, "Acme")


if __name__ == "__main__":
    unittest.main()


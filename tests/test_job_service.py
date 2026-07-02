import tempfile
import unittest
from pathlib import Path

from app.schemas.resume import NormalizedResume
from app.services.job_service import JobService


class JobServiceTest(unittest.TestCase):
    def test_create_job_from_url_persists_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = Path(tmpdir) / "workspace/walker"
            service = JobService(role_path)

            job = service.create_job_from_url("https://jobs.example.com/senior-frontend")

            self.assertEqual(job.title, "Senior Frontend")
            self.assertEqual(job.company, "jobs.example.com")
            self.assertEqual(service.list_jobs()[0].id, job.id)
            self.assertTrue((role_path / "jobs/jobs.json").is_file())

    def test_generate_output_writes_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = Path(tmpdir) / "workspace/walker"
            service = JobService(role_path)
            job = service.create_job_from_url("https://jobs.example.com/frontend")

            result = service.generate_output(
                job_id=job.id,
                kind="resume",
                resume=NormalizedResume(summary="Frontend engineer", skills=["Angular"]),
            )

            self.assertIsNotNone(result)
            output_path = role_path / result.path
            self.assertTrue(output_path.is_file())
            self.assertIn("Frontend engineer", output_path.read_text(encoding="utf-8"))

    def test_cover_letter_output_can_be_read_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = Path(tmpdir) / "workspace/walker"
            service = JobService(role_path)
            job = service.create_job_from_url("https://jobs.example.com/frontend")

            generated = service.generate_output(
                job_id=job.id,
                kind="cover_letter",
                resume=NormalizedResume(
                    name="Walker Lin",
                    title="Frontend Engineer",
                    summary="Builds reliable web apps",
                    skills=["Angular", "Docker"],
                ),
            )

            self.assertIsNotNone(generated)
            self.assertEqual(generated.kind, "cover-letter")
            self.assertIn("推薦信草稿", generated.content)
            output = service.get_output_by_path(generated.path)
            self.assertIsNotNone(output)
            self.assertIn("Walker Lin", output.content)
            self.assertEqual(
                service.list_outputs_by_job()[job.id]["cover-letter"].path,
                generated.path,
            )


if __name__ == "__main__":
    unittest.main()

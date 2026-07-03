import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.schemas.resume import NormalizedResume
from app.ai.cover_letter_generator import build_cover_letter_prompt
from app.ai.tailored_resume_generator import build_tailored_resume_prompt
from app.services.job_service import JobService


class FakeCoverLetterGenerator:
    calls = []

    def generate(self, *, resume: NormalizedResume, job, job_page_text: str = "") -> str:
        self.calls.append((resume.name, job.url, job_page_text))
        return f"我是 {resume.name}，想應徵 {job.url}。"


class FakeTailoredResumeGenerator:
    calls = []

    def generate(self, *, resume: NormalizedResume, job, job_page_text: str = "") -> str:
        self.calls.append((resume.name, job.url, job_page_text))
        return f"# {resume.name}\n\n## 專業摘要\n\n針對 {job.url} 的專用履歷。"


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

    def test_generate_output_writes_tailored_resume_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = Path(tmpdir) / "workspace/walker"
            service = JobService(role_path)
            job = service.create_job_from_url("https://jobs.example.com/frontend")
            FakeTailoredResumeGenerator.calls = []

            with patch(
                "app.services.job_service._fetch_job_page_text",
                return_value="Frontend role using Angular.",
            ):
                result = service.generate_output(
                    job_id=job.id,
                    kind="resume",
                    resume=NormalizedResume(
                        name="Walker Lin",
                        summary="Frontend engineer",
                        skills=["Angular"],
                    ),
                    tailored_resume_generator=FakeTailoredResumeGenerator(),
                )

            self.assertIsNotNone(result)
            output_path = role_path / result.path
            self.assertTrue(output_path.is_file())
            self.assertIn("專用履歷", output_path.read_text(encoding="utf-8"))
            self.assertEqual(
                FakeTailoredResumeGenerator.calls,
                [("Walker Lin", "https://jobs.example.com/frontend", "Frontend role using Angular.")],
            )

    def test_cover_letter_output_can_be_read_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = Path(tmpdir) / "workspace/walker"
            service = JobService(role_path)
            job = service.create_job_from_url("https://jobs.example.com/frontend")

            with patch(
                "app.services.job_service._fetch_job_page_text",
                return_value="Frontend role in a retail SaaS company using Angular.",
            ):
                generated = service.generate_output(
                    job_id=job.id,
                    kind="cover_letter",
                    resume=NormalizedResume(
                        name="Walker Lin",
                        title="Frontend Engineer",
                        summary="Builds reliable web apps",
                        skills=["Angular", "Docker"],
                    ),
                    cover_letter_generator=FakeCoverLetterGenerator(),
                )

            self.assertIsNotNone(generated)
            self.assertEqual(generated.kind, "cover-letter")
            self.assertIn("Walker Lin", generated.content)
            output = service.get_output_by_path(generated.path)
            self.assertIsNotNone(output)
            self.assertIn("Walker Lin", output.content)
            self.assertEqual(
                FakeCoverLetterGenerator.calls[-1],
                (
                    "Walker Lin",
                    "https://jobs.example.com/frontend",
                    "Frontend role in a retail SaaS company using Angular.",
                ),
            )
            self.assertEqual(
                service.list_outputs_by_job()[job.id]["cover-letter"].path,
                generated.path,
            )

    def test_cover_letter_requires_ai_generator(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = Path(tmpdir) / "workspace/walker"
            service = JobService(role_path)
            job = service.create_job_from_url("https://jobs.example.com/frontend")

            with self.assertRaises(RuntimeError):
                service.generate_output(
                    job_id=job.id,
                    kind="cover_letter",
                    resume=NormalizedResume(name="Walker Lin"),
                )

    def test_tailored_resume_requires_ai_generator(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            role_path = Path(tmpdir) / "workspace/walker"
            service = JobService(role_path)
            job = service.create_job_from_url("https://jobs.example.com/frontend")

            with self.assertRaises(RuntimeError):
                service.generate_output(
                    job_id=job.id,
                    kind="resume",
                    resume=NormalizedResume(name="Walker Lin"),
                )

    def test_cover_letter_prompt_includes_job_page_text_and_500_char_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = JobService(Path(tmpdir) / "workspace/walker")
            job = service.create_job_from_url("https://jobs.example.com/frontend")

            prompt = build_cover_letter_prompt(
                resume=NormalizedResume(
                    name="Walker Lin",
                    skills=["Angular", "Retail SaaS"],
                    summary="Builds reliable web products",
                ),
                job=job,
                job_page_text="Company builds retail SaaS and needs Angular testing experience.",
            )

            self.assertIn("500字內", prompt)
            self.assertIn("Company builds retail SaaS", prompt)
            self.assertIn("Angular", prompt)

    def test_tailored_resume_prompt_includes_job_page_text_and_no_fabrication_rule(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = JobService(Path(tmpdir) / "workspace/walker")
            job = service.create_job_from_url("https://jobs.example.com/frontend")

            prompt = build_tailored_resume_prompt(
                resume=NormalizedResume(
                    name="Walker Lin",
                    skills=["Angular", "Retail SaaS"],
                    summary="Builds reliable web products",
                ),
                job=job,
                job_page_text="Company builds retail SaaS and needs Angular testing experience.",
            )

            self.assertIn("專用履歷 Markdown", prompt)
            self.assertIn("不得新增不存在的公司", prompt)
            self.assertIn("Company builds retail SaaS", prompt)
            self.assertIn("Angular", prompt)


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from app.ai.cover_letter_generator import build_cover_letter_prompt
from app.ai.tailored_resume_generator import GeminiTailoredResumeGenerator, build_tailored_resume_prompt
from app.schemas.resume import NormalizedResume
from app.services.job_service import JobService, _fetch_job_page_text
from app.services.url_fetcher import UrlFetchResult


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


class FakeResumePdfExporter:
    calls = []

    def export(self, *, markdown, output_path: Path, job, resume: NormalizedResume) -> None:
        self.calls.append((markdown, output_path.name, job.id, resume.name))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"%PDF-1.4\nfake resume pdf\n")


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
            FakeResumePdfExporter.calls = []

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
                    resume_pdf_exporter=FakeResumePdfExporter(),
                )

            self.assertIsNotNone(result)
            output_path = role_path / result.path
            self.assertTrue(output_path.is_file())
            self.assertEqual(result.pdf_path, f"outputs/{job.id}-resume.pdf")
            self.assertTrue((role_path / result.pdf_path).is_file())
            self.assertIn("專用履歷", output_path.read_text(encoding="utf-8"))
            self.assertEqual(
                FakeTailoredResumeGenerator.calls,
                [("Walker Lin", "https://jobs.example.com/frontend", "Frontend role using Angular.")],
            )
            self.assertEqual(
                FakeResumePdfExporter.calls,
                [
                    (
                        "# Walker Lin\n\n## 專業摘要\n\n針對 https://jobs.example.com/frontend 的專用履歷。",
                        f"{job.id}-resume.pdf",
                        job.id,
                        "Walker Lin",
                    )
                ],
            )
            self.assertEqual(service.list_outputs_by_job()[job.id]["resume"].pdf_path, result.pdf_path)

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
            self.assertIn("請不要輸出水平分隔線", prompt)
            self.assertIn("直接輸出純網址", prompt)
            self.assertIn("請不要輸出個人檔案連結", prompt)
            self.assertIn("ATS 需求", prompt)
            self.assertIn("required skills", prompt)
            self.assertIn("請不要使用表格", prompt)
            self.assertIn("Markdown 粗體", prompt)
            self.assertIn("Company builds retail SaaS", prompt)
            self.assertIn("Angular", prompt)

    def test_gemini_tailored_resume_timeout_raises_runtime_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = JobService(Path(tmpdir) / "workspace/walker")
            job = service.create_job_from_url("https://jobs.example.com/frontend")
            generator = GeminiTailoredResumeGenerator(api_key="test-key", model="test-model")

            with (
                patch(
                    "app.ai.tailored_resume_generator.request.urlopen",
                    side_effect=TimeoutError("The read operation timed out"),
                ),
                redirect_stdout(StringIO()),
                self.assertRaisesRegex(RuntimeError, "Gemini API request timed out"),
            ):
                generator.generate(
                    resume=NormalizedResume(name="Walker Lin"),
                    job=job,
                    job_page_text="Frontend role using Angular.",
                )

    def test_fetch_job_page_text_uses_shared_url_fetcher(self) -> None:
        with patch(
            "app.services.job_service.fetch_url_text",
            return_value=UrlFetchResult(
                url="https://jobs.example.com/frontend",
                status="completed",
                text="Senior\n\nFrontend\tEngineer using Angular",
            ),
        ) as fetcher:
            text = _fetch_job_page_text("https://jobs.example.com/frontend")

        self.assertEqual(text, "Senior Frontend Engineer using Angular")
        fetcher.assert_called_once_with("https://jobs.example.com/frontend", timeout=10)

    def test_fetch_job_page_text_returns_empty_when_fetch_fails(self) -> None:
        with patch(
            "app.services.job_service.fetch_url_text",
            return_value=UrlFetchResult(
                url="https://jobs.example.com/frontend",
                status="failed",
                message="timeout",
            ),
        ):
            text = _fetch_job_page_text("https://jobs.example.com/frontend")

        self.assertEqual(text, "")


if __name__ == "__main__":
    unittest.main()

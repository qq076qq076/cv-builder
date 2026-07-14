import unittest
import tempfile
import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from app.ai.cover_letter_generator import GeminiCoverLetterGenerator, build_cover_letter_prompt
from app.ai.job_insights_generator import GeminiJobInsightsGenerator, _build_interview_prep_markdown
from app.ai.tailored_resume_generator import GeminiTailoredResumeGenerator, build_tailored_resume_prompt
from app.schemas.resume import NormalizedResume
from app.services.job_service import JobService, _clean_job_page_text, _fetch_job_page_text
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


class FakeGeminiResponse:
    def __init__(self, body: bytes = b'{"output_text": "Generated content"}') -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        pass

    def read(self) -> bytes:
        return self.body


class JobServiceTest(unittest.TestCase):
    def test_interview_prep_markdown_contains_all_categories_and_star_fields(self) -> None:
        question = {
            "question": "請說明你如何處理技術取捨？",
            "why_it_matters": "確認技術判斷能力。",
            "star_answer": {
                "situation": "專案需要在期限內完成。",
                "task": "負責評估方案。",
                "action": "比較方案並與團隊討論。",
                "result": "完成可維護的實作。",
            },
        }

        markdown = _build_interview_prep_markdown(
            {
                "technical": [question, question],
                "behavioral": [question, question],
                "management": [question, question],
                "project_deep_dive": [question, question],
            }
        )

        self.assertIn("## 技術問題", markdown)
        self.assertIn("## 行為問題", markdown)
        self.assertIn("## 管理能力問題", markdown)
        self.assertIn("## 專案深挖問題", markdown)
        self.assertIn("**Situation：** 專案需要在期限內完成。", markdown)
        self.assertIn("**Result：** 完成可維護的實作。", markdown)

    def test_gemini_interview_prep_accepts_interview_system_prompt(self) -> None:
        question = {
            "question": "請說明你的技術取捨？",
            "why_it_matters": "確認技術判斷。",
            "star_answer": {
                "situation": "情境",
                "task": "任務",
                "action": "行動",
                "result": "結果",
            },
        }
        response_body = json.dumps(
            {
                "output_text": json.dumps(
                    {
                        "technical": [question, question],
                        "behavioral": [question, question],
                        "management": [question, question],
                        "project_deep_dive": [question, question],
                    },
                    ensure_ascii=False,
                )
            },
            ensure_ascii=False,
        ).encode("utf-8")

        with patch(
            "app.ai.job_insights_generator.request.urlopen",
            return_value=FakeGeminiResponse(response_body),
        ):
            markdown = GeminiJobInsightsGenerator(api_key="test-key", model="test-model").generate_interview_prep(
                resume=NormalizedResume(name="Walker Lin"),
                job=type("Job", (), {"model_dump": lambda self, **kwargs: {"url": "https://jobs.example.com"}})(),
                job_page_text="Frontend role",
            )

        self.assertIn("## 技術問題", markdown)

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

    def test_generate_output_reuses_cached_job_description(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = JobService(Path(tmpdir) / "workspace/walker")
            job = service.create_job_from_url(
                "https://jobs.example.com/frontend",
                description="Cached Angular role description.",
            )
            FakeTailoredResumeGenerator.calls = []

            with patch("app.services.job_service._fetch_job_page_text") as fetcher:
                service.generate_output(
                    job_id=job.id,
                    kind="resume",
                    resume=NormalizedResume(name="Walker Lin"),
                    tailored_resume_generator=FakeTailoredResumeGenerator(),
                )

            fetcher.assert_not_called()
            self.assertEqual(FakeTailoredResumeGenerator.calls[-1][2], "Cached Angular role description.")

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

    def test_gemini_generators_set_request_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = JobService(Path(tmpdir) / "workspace/walker")
            job = service.create_job_from_url("https://jobs.example.com/frontend")
            resume = NormalizedResume(name="Walker Lin")

            with (
                patch(
                    "app.ai.tailored_resume_generator.request.urlopen",
                    return_value=FakeGeminiResponse(),
                ) as urlopen,
                redirect_stdout(StringIO()),
            ):
                content = GeminiTailoredResumeGenerator(api_key="test-key", model="test-model").generate(
                    resume=resume,
                    job=job,
                    job_page_text="Frontend role using Angular.",
                )

            self.assertEqual(content, "Generated content")
            self.assertEqual(urlopen.call_args.kwargs["timeout"], 120)

            with (
                patch(
                    "app.ai.cover_letter_generator.request.urlopen",
                    return_value=FakeGeminiResponse(),
                ) as urlopen,
                redirect_stdout(StringIO()),
            ):
                content = GeminiCoverLetterGenerator(api_key="test-key", model="test-model").generate(
                    resume=resume,
                    job=job,
                    job_page_text="Frontend role using Angular.",
                )

            self.assertEqual(content, "Generated content")
            self.assertEqual(urlopen.call_args.kwargs["timeout"], 120)

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

    def test_clean_job_page_text_removes_navigation_and_related_jobs_noise(self) -> None:
        raw_text = """
        登入
        註冊
        分享
        Senior Frontend Engineer
        ACME SaaS
        職務內容
        Build React and TypeScript products for merchant dashboards.
        Responsibilities
        Own frontend architecture and collaborate with backend engineers.
        Requirements
        React
        TypeScript
        GitLab CI/CD
        相似職缺
        Backend Engineer
        推薦職缺
        Privacy Policy
        Copyright 2026
        """

        cleaned = _clean_job_page_text(raw_text)

        self.assertIn("Senior Frontend Engineer", cleaned)
        self.assertIn("Build React and TypeScript products", cleaned)
        self.assertIn("Own frontend architecture", cleaned)
        self.assertIn("GitLab CI/CD", cleaned)
        self.assertNotIn("登入", cleaned)
        self.assertNotIn("分享", cleaned)
        self.assertNotIn("Backend Engineer", cleaned)
        self.assertNotIn("Privacy Policy", cleaned)

    def test_clean_job_page_text_deduplicates_lines_and_limits_length(self) -> None:
        raw_text = "\n".join(
            [
                "職務內容",
                "Python backend API development",
                "Python backend API development",
                "Requirements",
                "FastAPI " * 2000,
            ]
        )

        cleaned = _clean_job_page_text(raw_text, max_chars=200)

        self.assertEqual(cleaned.count("Python backend API development"), 1)
        self.assertLessEqual(len(cleaned), 200)


if __name__ == "__main__":
    unittest.main()

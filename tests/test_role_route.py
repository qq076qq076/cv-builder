import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas.evidence import EvidenceSource
from app.schemas.resume import NormalizedResume
from app.schemas.role import RoleProfile
from app.services.role_service import RoleService
from app.storage.evidence import EvidenceRepository
from app.storage.resume import ResumeRepository


class FakeCoverLetterGenerator:
    calls = []

    def __init__(self, *, api_key: str, model: str, log_path: Path | None = None) -> None:
        self.api_key = api_key
        self.model = model
        self.log_path = log_path

    def generate(self, *, resume, job, job_page_text: str = "") -> str:
        self.calls.append((self.api_key, self.model, resume.name, job.url, job_page_text))
        return f"我是 {resume.name}，針對 {job.url} 申請此職缺。"


class FakeTailoredResumeGenerator:
    calls = []

    def __init__(self, *, api_key: str, model: str, log_path: Path | None = None) -> None:
        self.api_key = api_key
        self.model = model
        self.log_path = log_path

    def generate(self, *, resume, job, job_page_text: str = "") -> str:
        self.calls.append((self.api_key, self.model, resume.name, job.url, job_page_text))
        return f"# {resume.name}\n\n針對 {job.url} 的專用履歷。"


class FakeResumeNormalizationService:
    calls = []

    def __init__(
        self,
        *,
        role_path: Path,
        api_key: str | None,
        model: str,
        gemini_api_key: str | None = None,
        gemini_model: str = "",
    ) -> None:
        self.role_path = role_path
        self.api_key = api_key
        self.model = model
        self.gemini_api_key = gemini_api_key
        self.gemini_model = gemini_model

    def normalize_source(self, source_id: str, *, target_language: str | None = None):
        from app.services.resume_normalization_service import ResumeNormalizationResult

        self.calls.append(source_id)
        return ResumeNormalizationResult(
            status="completed",
            resume=NormalizedResume(sourceIds=[source_id], name="Walker Lin", skills=["Python"]),
        )

    def normalize_sources(
        self,
        source_ids: list[str],
        *,
        target_language: str | None = None,
    ):
        from app.services.resume_normalization_service import ResumeNormalizationResult

        self.calls.append((tuple(source_ids), target_language))
        return ResumeNormalizationResult(
            status="completed",
            resume=NormalizedResume(sourceIds=source_ids, name="Walker Lin", skills=["Python"]),
        )


class FailingResumeNormalizationService(FakeResumeNormalizationService):
    def normalize_sources(
        self,
        source_ids: list[str],
        *,
        target_language: str | None = None,
    ):
        from app.services.resume_normalization_service import ResumeNormalizationResult

        self.calls.append((tuple(source_ids), target_language))
        return ResumeNormalizationResult(
            status="fetch_failed",
            message="URL 抓取階段失敗：Playwright 抓取逾時",
            error_stage="url_fetch",
        )


class RoleRouteTest(unittest.TestCase):
    def test_create_role_redirects_to_role_detail(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"

            response = self._client_for(workspace).post(
                "/roles",
                data={"role_name": "Walker"},
                follow_redirects=False,
            )

            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers["location"], "/roles/walker")
            self.assertTrue((workspace / "walker/evidence/profile.json").is_file())

    def test_saved_sources_count_as_role_content(self) -> None:
        from app.routes.roles import _has_role_content

        source = EvidenceSource(
            id="src_1",
            label="104 銀行",
            path="evidence/files/src_1.txt",
            originalFilename="src_1.txt",
            contentType="text/plain",
            sourceUrl="https://pda.104.com.tw/profile/share/demo",
            sizeBytes=12,
            extractionStatus="failed",
            createdAt=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )

        self.assertTrue(_has_role_content(RoleProfile(), NormalizedResume(), [source]))

    def test_role_detail_shows_profile_form(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            RoleService(workspace).create_role("Walker")

            response = self._client_for(workspace).get("/roles/walker")

            self.assertEqual(response.status_code, 200)
            self.assertIn("尚未建立個人資訊", response.text)
            self.assertIn("開始初始化", response.text)
            self.assertIn('action="/roles/walker/initialize"', response.text)
            self.assertIn("data-loading-form", response.text)
            self.assertIn('data-loading-label="初始化中"', response.text)
            self.assertIn("data-language-popup", response.text)
            self.assertIn('name="target_language"', response.text)
            self.assertIn('name="source_url"', response.text)
            self.assertNotIn("Evidence 來源", response.text)
            self.assertNotIn("姓名</span>", response.text)

    def test_initialize_role_saves_sources_and_normalizes_together(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            RoleService(workspace).create_role("Walker")
            FakeResumeNormalizationService.calls = []

            with patch(
                "app.routes.roles.ResumeNormalizationService",
                FakeResumeNormalizationService,
            ):
                response = self._client_for(workspace).post(
                    "/roles/walker/initialize",
                    data={
                        "source_url": [
                            "https://www.linkedin.com/in/walker",
                            "https://www.cake.me/walker",
                        ]
                    },
                    files={"resume_file": ("resume.txt", b"Senior Python Engineer", "text/plain")},
                )

            self.assertEqual(response.status_code, 200)
            sources = EvidenceRepository(workspace / "walker").list_sources().sources
            self.assertEqual(len(sources), 3)
            self.assertEqual(
                FakeResumeNormalizationService.calls,
                [(tuple(source.id for source in sources), "zh")],
            )
            self.assertIn("已整合 3 筆來源並完成初始化。", response.text)
            self.assertEqual(RoleService(workspace).load_profile("walker").name, "Walker Lin")

    def test_initialize_failure_with_saved_sources_shows_detail_view(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            RoleService(workspace).create_role("Walker")
            FailingResumeNormalizationService.calls = []

            with patch(
                "app.routes.roles.ResumeNormalizationService",
                FailingResumeNormalizationService,
            ):
                response = self._client_for(workspace).post(
                    "/roles/walker/initialize",
                    data={
                        "source_url": ["https://pda.104.com.tw/profile/share/demo"],
                        "target_language": "zh",
                    },
                )

            self.assertEqual(response.status_code, 200)
            self.assertIn("URL 抓取階段失敗", response.text)
            self.assertIn("Evidence 來源", response.text)
            self.assertIn("104 銀行", response.text)
            self.assertNotIn("尚未建立個人資訊", response.text)
            self.assertNotIn("開始初始化", response.text)

    def test_initialize_role_passes_selected_language(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            RoleService(workspace).create_role("Walker")
            FakeResumeNormalizationService.calls = []

            with patch(
                "app.routes.roles.ResumeNormalizationService",
                FakeResumeNormalizationService,
            ):
                response = self._client_for(workspace).post(
                    "/roles/walker/initialize",
                    data={
                        "source_url": ["https://www.linkedin.com/in/walker"],
                        "target_language": "en",
                    },
                )

            self.assertEqual(response.status_code, 200)
            sources = EvidenceRepository(workspace / "walker").list_sources().sources
            self.assertEqual(
                FakeResumeNormalizationService.calls,
                [(tuple(source.id for source in sources), "en")],
            )

    def test_update_profile_writes_to_role_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            RoleService(workspace).create_role("Walker")

            response = self._client_for(workspace).post(
                "/roles/walker/profile",
                data={
                    "name": "Walker Lin",
                    "skills": "Python",
                    "career": "Frontend",
                    "autobiography": "Bio",
                },
                follow_redirects=False,
            )

            self.assertEqual(response.status_code, 303)
            profile = RoleService(workspace).load_profile("walker")
            self.assertEqual(profile.name, "Walker Lin")
            self.assertEqual(profile.skills, "Python")

    def test_role_detail_with_profile_shows_editable_resume_panels(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            role_service = RoleService(workspace)
            role_service.create_role("Walker")
            role_service.save_profile("walker", RoleProfile(name="Walker Lin"))

            response = self._client_for(workspace).get("/roles/walker")

            self.assertEqual(response.status_code, 200)
            self.assertIn("個人概要", response.text)
            self.assertIn("material-symbols-outlined edit-icon", response.text)
            self.assertIn("Walker Lin", response.text)
            self.assertNotIn('href="/roles/walker/import">上傳履歷', response.text)
            self.assertNotIn("手動編輯個人資訊", response.text)
            self.assertNotIn("AI 匹配強度分析", response.text)

    def test_role_detail_shows_evidence_management_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            role_service = RoleService(workspace)
            role_service.create_role("Walker")
            role_service.save_profile("walker", RoleProfile(name="Walker Lin"))
            role_path = workspace / "walker"
            EvidenceRepository(role_path).add_source(
                EvidenceSource(
                    id="src_1",
                    label="resume.txt",
                    path="evidence/files/src_1_resume.txt",
                    originalFilename="resume.txt",
                    contentType="text/plain",
                    sizeBytes=12,
                    contentHash="hash1",
                    extractionStatus="completed",
                    createdAt=datetime(2026, 7, 1, tzinfo=timezone.utc),
                )
            )
            EvidenceRepository(role_path).add_source(
                EvidenceSource(
                    id="src_empty_url",
                    type="url",
                    label="Yourator",
                    path="evidence/files/src_empty_url.txt",
                    originalFilename="src_empty_url.txt",
                    contentType="text/plain",
                    sizeBytes=0,
                    contentHash="hash2",
                    extractionStatus="not_required",
                    createdAt=datetime(2026, 7, 1, tzinfo=timezone.utc),
                )
            )

            response = self._client_for(workspace).get("/roles/walker")

            self.assertEqual(response.status_code, 200)
            self.assertIn("Multi-source registry", response.text)
            self.assertIn("panel-editor evidence-source-editor", response.text)
            self.assertIn(
                '<summary class="material-symbols-outlined edit-icon">edit</summary>', response.text
            )
            self.assertIn("evidence-source-edit-form", response.text)
            self.assertIn('action="/roles/walker/sources"', response.text)
            self.assertIn('name="source_url"', response.text)
            self.assertIn('action="/roles/walker/sources/normalize"', response.text)
            self.assertIn("解析資料", response.text)
            self.assertIn('data-loading-label="解析中"', response.text)
            self.assertIn("data-language-popup", response.text)
            self.assertIn('name="target_language"', response.text)
            self.assertIn('data-language-choice="zh"', response.text)
            self.assertIn('data-language-choice="en"', response.text)
            self.assertIn("resume.txt", response.text)
            self.assertNotIn("src_empty_url", response.text)
            self.assertNotIn("詳細資料", response.text)
            self.assertNotIn('href="/roles/walker/import"', response.text)

    def test_update_role_sources_saves_url_sources_without_normalizing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            role_service = RoleService(workspace)
            role_service.create_role("Walker")
            role_service.save_profile("walker", RoleProfile(name="Walker Lin"))

            response = self._client_for(workspace).post(
                "/roles/walker/sources",
                data={
                    "source_platform": ["linkedin", "104", "cake", "yourator"],
                    "source_url": [
                        "https://www.linkdin.com/in/walker",
                        "",
                        "",
                        "https://www.yourator.co/users/walker",
                    ],
                },
            )

            self.assertEqual(response.status_code, 200)
            sources = EvidenceRepository(workspace / "walker").list_sources().sources
            self.assertEqual(len(sources), 2)
            self.assertEqual([source.type for source in sources], ["url", "url"])
            self.assertEqual(sources[0].label, "LinkedIn")
            self.assertEqual(sources[0].source_url, "https://www.linkdin.com/in/walker")
            self.assertIn("已更新 2 筆來源。", response.text)
            self.assertIn("<h3>LinkedIn</h3>", response.text)
            self.assertIn('href="https://www.linkdin.com/in/walker"', response.text)
            self.assertIn('value="https://www.linkdin.com/in/walker"', response.text)
            self.assertIn('value="https://www.yourator.co/users/walker"', response.text)
            self.assertRegex(
                response.text,
                r'<article class="app-source-item evidence-source-card">[\s\S]*?'
                r'<span class="material-symbols-outlined">share</span>[\s\S]*?'
                r"<h3>LinkedIn</h3>",
            )
            self.assertRegex(
                response.text,
                r'<article class="app-source-item evidence-source-card">[\s\S]*?'
                r'<span class="material-symbols-outlined">rocket_launch</span>[\s\S]*?'
                r"<h3>Yourator</h3>",
            )
            self.assertIn('target="_blank"', response.text)
            self.assertNotIn("www.linkedin.com-in-walker.txt", response.text)

            update_response = self._client_for(workspace).post(
                "/roles/walker/sources",
                data={
                    "source_platform": ["linkedin", "104", "cake", "yourator"],
                    "source_url": [
                        "https://www.linkedin.com/in/walker-lin",
                        "",
                        "",
                        "",
                    ],
                },
            )

            self.assertEqual(update_response.status_code, 200)
            updated_sources = EvidenceRepository(workspace / "walker").list_sources().sources
            self.assertEqual(len(updated_sources), 1)
            self.assertEqual(updated_sources[0].label, "LinkedIn")
            self.assertEqual(
                updated_sources[0].source_url,
                "https://www.linkedin.com/in/walker-lin",
            )
            self.assertIn('value="https://www.linkedin.com/in/walker-lin"', update_response.text)
            self.assertNotIn('href="https://www.yourator.co/users/walker"', update_response.text)

    def test_normalize_all_sources_processes_multiple_evidence_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            RoleService(workspace).create_role("Walker")
            role_path = workspace / "walker"
            repository = EvidenceRepository(role_path)
            for source_id in ("src_1", "src_2"):
                repository.add_source(
                    EvidenceSource(
                        id=source_id,
                        label=f"{source_id}.txt",
                        path=f"evidence/files/{source_id}.txt",
                        originalFilename=f"{source_id}.txt",
                        contentType="text/plain",
                        sizeBytes=12,
                        contentHash=source_id,
                        extractionStatus="completed",
                        createdAt=datetime(2026, 7, 1, tzinfo=timezone.utc),
                    )
                )
            FakeResumeNormalizationService.calls = []

            with patch(
                "app.routes.roles.ResumeNormalizationService",
                FakeResumeNormalizationService,
            ):
                response = self._client_for(workspace).post("/roles/walker/sources/normalize")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(FakeResumeNormalizationService.calls, [(("src_1", "src_2"), "zh")])
            self.assertIn("已整合 2 筆 Evidence 來源。", response.text)
            self.assertEqual(RoleService(workspace).load_profile("walker").name, "Walker Lin")

    def test_normalize_all_sources_passes_selected_language(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            RoleService(workspace).create_role("Walker")
            role_path = workspace / "walker"
            EvidenceRepository(role_path).add_source(
                EvidenceSource(
                    id="src_1",
                    label="resume.txt",
                    path="evidence/files/src_1.txt",
                    originalFilename="resume.txt",
                    contentType="text/plain",
                    sizeBytes=12,
                    contentHash="src_1",
                    extractionStatus="completed",
                    createdAt=datetime(2026, 7, 1, tzinfo=timezone.utc),
                )
            )
            FakeResumeNormalizationService.calls = []

            with patch(
                "app.routes.roles.ResumeNormalizationService",
                FakeResumeNormalizationService,
            ):
                response = self._client_for(workspace).post(
                    "/roles/walker/sources/normalize",
                    data={"target_language": "en"},
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(FakeResumeNormalizationService.calls, [(("src_1",), "en")])

    def test_update_resume_profile_writes_resume_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            RoleService(workspace).create_role("Walker")

            response = self._client_for(workspace).post(
                "/roles/walker/resume/profile",
                data={
                    "name": "Walker Lin",
                    "title": "Senior Frontend Engineer",
                    "summary": "Builds web products",
                    "autobiography": "Bio",
                },
                follow_redirects=False,
            )

            self.assertEqual(response.status_code, 303)
            resume = ResumeRepository(workspace / "walker").load()
            self.assertEqual(resume.name, "Walker Lin")
            self.assertEqual(resume.title, "Senior Frontend Engineer")
            self.assertEqual(resume.summary, "Builds web products")

    def test_update_resume_skills_writes_resume_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            RoleService(workspace).create_role("Walker")

            response = self._client_for(workspace).post(
                "/roles/walker/resume/skills",
                data={"skills": "Angular\nDocker"},
                follow_redirects=False,
            )

            self.assertEqual(response.status_code, 303)
            resume = ResumeRepository(workspace / "walker").load()
            self.assertEqual(resume.skills, ["Angular", "Docker"])

    def test_update_resume_experiences_writes_resume_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            RoleService(workspace).create_role("Walker")

            response = self._client_for(workspace).post(
                "/roles/walker/resume/experiences",
                data={
                    "experiences": (
                        "title: Senior Frontend Engineer\n"
                        "company: Kabob\n"
                        "period: Sep. 2022 - Present\n"
                        "summary: Built SaaS products\n"
                        "achievements: Led team, Improved CI\n"
                        "technologies: Angular, Docker"
                    )
                },
                follow_redirects=False,
            )

            self.assertEqual(response.status_code, 303)
            resume = ResumeRepository(workspace / "walker").load()
            self.assertEqual(resume.experiences[0].title, "Senior Frontend Engineer")
            self.assertEqual(resume.experiences[0].company, "Kabob")
            self.assertEqual(resume.experiences[0].technologies, ["Angular", "Docker"])

    def test_update_resume_contact_languages_and_projects(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            RoleService(workspace).create_role("Walker")
            client = self._client_for(workspace)

            client.post(
                "/roles/walker/resume/contact",
                data={
                    "email": "walker@example.com",
                    "phone": "0912",
                    "location": "Taipei",
                    "links": "https://example.com",
                },
            )
            client.post(
                "/roles/walker/resume/languages",
                data={"languages": "Mandarin | Native\nEnglish | Intermediate"},
            )
            response = client.post(
                "/roles/walker/resume/projects",
                data={
                    "projects": (
                        "name: WEBA\n"
                        "role: Frontend\n"
                        "description: Customer communication platform\n"
                        "technologies: Vue, TypeScript\n"
                        "outcomes: Launched product"
                    )
                },
                follow_redirects=False,
            )

            self.assertEqual(response.status_code, 303)
            resume = ResumeRepository(workspace / "walker").load()
            self.assertEqual(resume.contact.email, "walker@example.com")
            self.assertEqual(resume.languages[1].name, "English")
            self.assertEqual(resume.projects[0].name, "WEBA")

    def test_update_resume_education_writes_resume_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            RoleService(workspace).create_role("Walker")

            response = self._client_for(workspace).post(
                "/roles/walker/resume/education",
                data={
                    "education": "Chien Hsin University | Bachelor | CSIE | 2011 | 2015",
                    "certificates": "AWS SAA | AWS | 2023",
                },
                follow_redirects=False,
            )

            self.assertEqual(response.status_code, 303)
            resume = ResumeRepository(workspace / "walker").load()
            self.assertEqual(resume.education[0].school, "Chien Hsin University")
            self.assertEqual(resume.certificates[0].issuer, "AWS")

    def test_update_resume_repeatable_fields_write_resume_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            RoleService(workspace).create_role("Walker")
            client = self._client_for(workspace)

            client.post(
                "/roles/walker/resume/skills",
                data={"skill_items": ["Angular", "Docker"]},
            )
            client.post(
                "/roles/walker/resume/experiences",
                data={
                    "experience_title": ["Senior Frontend Engineer"],
                    "experience_company": ["Kabob"],
                    "experience_period": ["Sep. 2022 - Present"],
                    "experience_summary": ["Built SaaS products"],
                    "experience_achievements": ["Led team, Improved CI"],
                    "experience_technologies": ["Angular, Docker"],
                },
            )
            client.post(
                "/roles/walker/resume/projects",
                data={
                    "project_name": ["WEBA"],
                    "project_role": ["Frontend"],
                    "project_description": ["Customer communication platform"],
                    "project_technologies": ["Vue, TypeScript"],
                    "project_outcomes": ["Launched product"],
                },
            )
            client.post(
                "/roles/walker/resume/education",
                data={
                    "education_school": ["Chien Hsin University"],
                    "education_degree": ["Bachelor"],
                    "education_major": ["CSIE"],
                    "education_period": ["2011 - 2015"],
                    "certificate_name": ["AWS SAA"],
                    "certificate_issuer": ["AWS"],
                    "certificate_date": ["2023"],
                },
            )
            response = client.post(
                "/roles/walker/resume/languages",
                data={
                    "language_name": ["Mandarin"],
                    "language_proficiency": ["Native"],
                },
                follow_redirects=False,
            )

            self.assertEqual(response.status_code, 303)
            resume = ResumeRepository(workspace / "walker").load()
            self.assertEqual(resume.skills, ["Angular", "Docker"])
            self.assertEqual(resume.experiences[0].company, "Kabob")
            self.assertEqual(resume.experiences[0].technologies, ["Angular", "Docker"])
            self.assertEqual(resume.projects[0].name, "WEBA")
            self.assertEqual(resume.education[0].start_date, "2011")
            self.assertEqual(resume.certificates[0].name, "AWS SAA")
            self.assertEqual(resume.languages[0].proficiency, "Native")

    def test_create_job_route_writes_role_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            RoleService(workspace).create_role("Walker")

            response = self._client_for(workspace).post(
                "/roles/walker/jobs",
                data={"job_url": "https://jobs.example.com/senior-frontend"},
                follow_redirects=False,
            )

            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers["location"], "/roles/walker#jobs")
            self.assertTrue((workspace / "walker/jobs/jobs.json").is_file())

    def test_role_detail_lists_tracked_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            role_service = RoleService(workspace)
            role_service.create_role("Walker")
            role_service.save_profile("walker", RoleProfile(name="Walker Lin"))
            client = self._client_for(workspace)
            client.post(
                "/roles/walker/jobs",
                data={"job_url": "https://jobs.example.com/senior-frontend"},
            )

            response = client.get("/roles/walker")

            self.assertEqual(response.status_code, 200)
            self.assertIn("職缺追蹤清單", response.text)
            self.assertIn("Senior Frontend", response.text)
            self.assertIn('data-loading-label="生成專用履歷中"', response.text)
            self.assertIn('data-loading-label="生成推薦信中"', response.text)
            self.assertIn("button-spinner", response.text)

    def test_generate_job_output_route_writes_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            RoleService(workspace).create_role("Walker")
            FakeTailoredResumeGenerator.calls = []
            client = self._client_for(workspace, openai_api_key="openai-key")
            client.post(
                "/roles/walker/resume/profile",
                data={"name": "Walker Lin", "summary": "Frontend engineer"},
            )
            client.post(
                "/roles/walker/jobs",
                data={"job_url": "https://jobs.example.com/senior-frontend"},
            )
            jobs_path = workspace / "walker/jobs/jobs.json"
            job_id = json.loads(jobs_path.read_text(encoding="utf-8"))["jobs"][0]["id"]

            with (
                patch(
                    "app.routes.roles.OpenAITailoredResumeGenerator",
                    FakeTailoredResumeGenerator,
                ),
                patch(
                    "app.services.job_service._fetch_job_page_text",
                    return_value="Senior frontend role for a jobs platform using Angular.",
                ),
            ):
                response = client.post(
                    f"/roles/walker/jobs/{job_id}/generate",
                    data={"kind": "resume"},
                    follow_redirects=False,
                )

            self.assertEqual(response.status_code, 303)
            self.assertEqual(
                response.headers["location"],
                f"/roles/walker?generated_output=outputs/{job_id}-resume.md#jobs",
            )
            self.assertTrue((workspace / f"walker/outputs/{job_id}-resume.md").is_file())
            self.assertEqual(
                FakeTailoredResumeGenerator.calls,
                [
                    (
                        "openai-key",
                        "gpt-4.1-mini",
                        "Walker Lin",
                        "https://jobs.example.com/senior-frontend",
                        "Senior frontend role for a jobs platform using Angular.",
                    )
                ],
            )
            page = client.get(response.headers["location"])
            self.assertEqual(page.status_code, 200)
            self.assertIn("專用履歷草稿", page.text)
            self.assertIn("查看專用履歷", page.text)
            self.assertIn("重新生成專用履歷", page.text)
            self.assertIn('data-loading-label="生成專用履歷中"', page.text)
            self.assertIn("針對 https://jobs.example.com/senior-frontend 的專用履歷", page.text)

    def test_generate_cover_letter_shows_popup_and_existing_button(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            RoleService(workspace).create_role("Walker")
            FakeCoverLetterGenerator.calls = []
            client = self._client_for(workspace, openai_api_key="openai-key")
            client.post(
                "/roles/walker/resume/profile",
                data={
                    "name": "Walker Lin",
                    "title": "Frontend Engineer",
                    "summary": "Builds reliable web apps",
                },
            )
            client.post(
                "/roles/walker/jobs",
                data={"job_url": "https://jobs.example.com/senior-frontend"},
            )
            jobs_path = workspace / "walker/jobs/jobs.json"
            job_id = json.loads(jobs_path.read_text(encoding="utf-8"))["jobs"][0]["id"]

            with (
                patch(
                    "app.routes.roles.OpenAICoverLetterGenerator",
                    FakeCoverLetterGenerator,
                ),
                patch(
                    "app.services.job_service._fetch_job_page_text",
                    return_value="Senior frontend role for a jobs platform using Angular.",
                ),
            ):
                response = client.post(
                    f"/roles/walker/jobs/{job_id}/generate",
                    data={"kind": "cover_letter"},
                    follow_redirects=False,
                )

            self.assertEqual(response.status_code, 303)
            self.assertEqual(
                response.headers["location"],
                f"/roles/walker?generated_output=outputs/{job_id}-cover-letter.md#jobs",
            )
            self.assertEqual(
                FakeCoverLetterGenerator.calls,
                [
                    (
                        "openai-key",
                        "gpt-4.1-mini",
                        "Walker Lin",
                        "https://jobs.example.com/senior-frontend",
                        "Senior frontend role for a jobs platform using Angular.",
                    )
                ],
            )
            page = client.get(response.headers["location"])
            self.assertEqual(page.status_code, 200)
            self.assertIn("針對 https://jobs.example.com/senior-frontend 申請此職缺", page.text)
            self.assertIn("Walker Lin", page.text)
            self.assertIn("查看推薦信", page.text)
            self.assertIn("重新生成推薦信", page.text)
            self.assertIn('data-loading-label="生成推薦信中"', page.text)

    def test_generate_cover_letter_without_api_key_shows_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            RoleService(workspace).create_role("Walker")
            client = self._client_for(workspace, openai_api_key="")
            client.post(
                "/roles/walker/resume/profile",
                data={"name": "Walker Lin", "summary": "Frontend engineer"},
            )
            client.post(
                "/roles/walker/jobs",
                data={"job_url": "https://jobs.example.com/senior-frontend"},
            )
            jobs_path = workspace / "walker/jobs/jobs.json"
            job_id = json.loads(jobs_path.read_text(encoding="utf-8"))["jobs"][0]["id"]

            response = client.post(
                f"/roles/walker/jobs/{job_id}/generate",
                data={"kind": "cover_letter"},
                follow_redirects=True,
            )

            self.assertEqual(response.status_code, 200)
            self.assertIn("生成失敗", response.text)
            self.assertIn("缺少 OPENAI_API_KEY 或 GEMINI_API_KEY", response.text)

    def test_generate_tailored_resume_without_api_key_shows_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            RoleService(workspace).create_role("Walker")
            client = self._client_for(workspace, openai_api_key="")
            client.post(
                "/roles/walker/resume/profile",
                data={"name": "Walker Lin", "summary": "Frontend engineer"},
            )
            client.post(
                "/roles/walker/jobs",
                data={"job_url": "https://jobs.example.com/senior-frontend"},
            )
            jobs_path = workspace / "walker/jobs/jobs.json"
            job_id = json.loads(jobs_path.read_text(encoding="utf-8"))["jobs"][0]["id"]

            response = client.post(
                f"/roles/walker/jobs/{job_id}/generate",
                data={"kind": "resume"},
                follow_redirects=True,
            )

            self.assertEqual(response.status_code, 200)
            self.assertIn("生成失敗", response.text)
            self.assertIn("缺少 OPENAI_API_KEY 或 GEMINI_API_KEY", response.text)

    def test_normalize_source_without_api_key_shows_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            RoleService(workspace).create_role("Walker")
            role_path = workspace / "walker"
            source_path = role_path / "evidence/files/src_1_resume.txt"
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_text("resume text", encoding="utf-8")
            EvidenceRepository(role_path).add_source(
                EvidenceSource(
                    id="src_1",
                    label="resume.txt",
                    path="evidence/files/src_1_resume.txt",
                    originalFilename="resume.txt",
                    contentType="text/plain",
                    sizeBytes=11,
                    extractionStatus="not_required",
                    createdAt=datetime(2026, 7, 1, tzinfo=timezone.utc),
                )
            )

            response = self._client_for(workspace, openai_api_key="").post(
                "/roles/walker/sources/src_1/normalize"
            )

            self.assertEqual(response.status_code, 200)
            self.assertIn("缺少 OPENAI_API_KEY 或 GEMINI_API_KEY", response.text)

    def _client_for(self, workspace: Path, openai_api_key: str | None = None) -> TestClient:
        env = {"CV_BUILDER_WORKSPACE": str(workspace)}
        if openai_api_key is not None:
            env["OPENAI_API_KEY"] = openai_api_key
        env["GEMINI_API_KEY"] = ""
        patcher = patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        return TestClient(create_app())


if __name__ == "__main__":
    unittest.main()

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
from app.schemas.role import RoleProfile
from app.services.role_service import RoleService
from app.storage.evidence import EvidenceRepository
from app.storage.resume import ResumeRepository


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

    def test_role_detail_shows_profile_form(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            RoleService(workspace).create_role("Walker")

            response = self._client_for(workspace).get("/roles/walker")

            self.assertEqual(response.status_code, 200)
            self.assertIn("尚未建立個人資訊", response.text)
            self.assertIn("上傳履歷", response.text)
            self.assertNotIn("姓名</span>", response.text)

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
            self.assertNotIn("手動編輯個人資訊", response.text)
            self.assertNotIn("AI 匹配強度分析", response.text)

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

    def test_generate_job_output_route_writes_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            RoleService(workspace).create_role("Walker")
            self._client_for(workspace).post(
                "/roles/walker/jobs",
                data={"job_url": "https://jobs.example.com/senior-frontend"},
            )
            jobs_path = workspace / "walker/jobs/jobs.json"
            job_id = json.loads(jobs_path.read_text(encoding="utf-8"))["jobs"][0]["id"]

            response = self._client_for(workspace).post(
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

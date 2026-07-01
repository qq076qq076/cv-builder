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

    def test_role_detail_with_profile_shows_profile_form(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            role_service = RoleService(workspace)
            role_service.create_role("Walker")
            role_service.save_profile("walker", RoleProfile(name="Walker Lin"))

            response = self._client_for(workspace).get("/roles/walker")

            self.assertEqual(response.status_code, 200)
            self.assertIn("個人資訊", response.text)
            self.assertIn("Walker Lin", response.text)

    def test_normalize_source_without_api_key_shows_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            RoleService(workspace).create_role("Walker")
            role_path = workspace / "walker"
            extracted_path = role_path / "evidence/extracted/src_1.txt"
            extracted_path.parent.mkdir(parents=True, exist_ok=True)
            extracted_path.write_text("resume text", encoding="utf-8")
            EvidenceRepository(role_path).add_source(
                EvidenceSource(
                    id="src_1",
                    label="resume.txt",
                    path="evidence/files/src_1_resume.txt",
                    originalFilename="resume.txt",
                    contentType="text/plain",
                    sizeBytes=11,
                    extractedTextPath="evidence/extracted/src_1.txt",
                    extractionStatus="completed",
                    createdAt=datetime(2026, 7, 1, tzinfo=timezone.utc),
                )
            )

            response = self._client_for(workspace, openai_api_key="").post(
                "/roles/walker/sources/src_1/normalize"
            )

            self.assertEqual(response.status_code, 200)
            self.assertIn("缺少 OPENAI_API_KEY", response.text)

    def _client_for(self, workspace: Path, openai_api_key: str | None = None) -> TestClient:
        env = {"CV_BUILDER_WORKSPACE": str(workspace)}
        if openai_api_key is not None:
            env["OPENAI_API_KEY"] = openai_api_key
        patcher = patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        return TestClient(create_app())


if __name__ == "__main__":
    unittest.main()

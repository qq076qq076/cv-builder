import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import create_app
from app.services.role_service import RoleService


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
            self.assertIn("個人資訊", response.text)
            self.assertIn("上傳履歷", response.text)

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

    def _client_for(self, workspace: Path) -> TestClient:
        patcher = patch.dict(os.environ, {"CV_BUILDER_WORKSPACE": str(workspace)})
        patcher.start()
        self.addCleanup(patcher.stop)
        return TestClient(create_app())


if __name__ == "__main__":
    unittest.main()

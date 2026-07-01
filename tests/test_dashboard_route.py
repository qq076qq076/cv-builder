import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import create_app
from app.services.role_service import RoleService


class DashboardRouteTest(unittest.TestCase):
    def test_health_endpoint_returns_ok(self) -> None:
        client = TestClient(create_app())

        response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_missing_workspace_prompts_create_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"

            response = self._get_dashboard(workspace)

        self.assertEqual(response.status_code, 200)
        self.assertIn("新增角色", response.text)
        self.assertIn("新增角色時會自動建立 workspace", response.text)

    def test_empty_workspace_prompts_import_or_manual_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()

            response = self._get_dashboard(workspace)

        self.assertEqual(response.status_code, 200)
        self.assertIn("新增角色", response.text)
        self.assertIn("目前沒有角色", response.text)

    def test_workspace_with_role_lists_role(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            RoleService(workspace).create_role("Walker")

            response = self._get_dashboard(workspace)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Walker", response.text)
        self.assertIn("/roles/walker", response.text)

    def _get_dashboard(self, workspace: Path):
        with patch.dict(os.environ, {"CV_BUILDER_WORKSPACE": str(workspace)}):
            client = TestClient(create_app())
            return client.get("/")


if __name__ == "__main__":
    unittest.main()

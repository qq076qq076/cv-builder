import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import create_app


class WorkspaceRouteTest(unittest.TestCase):
    def test_workspace_page_prompts_create_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            response = self._client_for(workspace).get("/workspace")

        self.assertEqual(response.status_code, 200)
        self.assertIn("建立工作區", response.text)
        self.assertIn("建立預設工作區", response.text)

    def test_create_workspace_creates_required_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            response = self._client_for(workspace).post("/workspace/create", follow_redirects=False)

            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers["location"], "/")
            self.assertTrue((workspace / "evidence/files").is_dir())
            self.assertTrue((workspace / "evidence/extracted").is_dir())
            self.assertTrue((workspace / "jobs").is_dir())
            self.assertTrue((workspace / "outputs").is_dir())
            self.assertTrue((workspace / "versions").is_dir())

    def _client_for(self, workspace: Path) -> TestClient:
        patcher = patch.dict(os.environ, {"CV_BUILDER_WORKSPACE": str(workspace)})
        patcher.start()
        self.addCleanup(patcher.stop)
        return TestClient(create_app())


if __name__ == "__main__":
    unittest.main()

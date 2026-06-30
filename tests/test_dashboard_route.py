import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import create_app


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
        self.assertIn("尚未建立本機工作區", response.text)
        self.assertIn("建立工作區", response.text)

    def test_empty_workspace_prompts_import_or_manual_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()

            response = self._get_dashboard(workspace)

        self.assertEqual(response.status_code, 200)
        self.assertIn("開始建立你的職涯資料", response.text)
        self.assertIn("上傳履歷", response.text)
        self.assertIn("手動輸入", response.text)

    def test_workspace_with_career_data_shows_career_summary_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()
            self._write_json(
                workspace / "career.json",
                {
                    "schemaVersion": 1,
                    "profile": {"name": "王小明"},
                    "experiences": [],
                    "projects": [],
                    "skills": [],
                },
            )

            response = self._get_dashboard(workspace)

        self.assertEqual(response.status_code, 200)
        self.assertIn("已建立職涯知識庫", response.text)
        self.assertIn("編輯職涯知識庫", response.text)

    def _get_dashboard(self, workspace: Path):
        with patch.dict(os.environ, {"CV_BUILDER_WORKSPACE": str(workspace)}):
            client = TestClient(create_app())
            return client.get("/")

    def _write_json(self, path: Path, data: dict) -> None:
        path.write_text(json.dumps(data), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.storage.workspace import ensure_workspace_dirs
from app.main import create_app


class ImportRouteTest(unittest.TestCase):
    def test_import_page_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            ensure_workspace_dirs(workspace)

            response = self._client_for(workspace).get("/import")

        self.assertEqual(response.status_code, 200)
        self.assertIn("上傳履歷", response.text)
        self.assertIn("/import/files", response.text)

    def test_import_page_prompts_workspace_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"

            response = self._client_for(workspace).get("/import")

        self.assertEqual(response.status_code, 200)
        self.assertIn("需要先建立工作區", response.text)
        self.assertIn("/workspace", response.text)

    def test_upload_file_returns_received_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            ensure_workspace_dirs(workspace)

            response = self._client_for(workspace).post(
                "/import/files",
                files={"resume_file": ("resume.txt", b"hello", "text/plain")},
            )

            self.assertEqual(response.status_code, 200)
            self.assertIn("已保存檔案", response.text)
            self.assertIn("resume.txt", response.text)
            self.assertIn("文字預覽", response.text)
            self.assertIn("hello", response.text)
            self.assertTrue((workspace / "evidence/sources.json").is_file())
            self.assertEqual(len(list((workspace / "evidence/files").iterdir())), 1)
            self.assertEqual(len(list((workspace / "evidence/extracted").iterdir())), 1)

    def test_upload_pdf_shows_unsupported_extraction_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            ensure_workspace_dirs(workspace)

            response = self._client_for(workspace).post(
                "/import/files",
                files={"resume_file": ("resume.pdf", b"%PDF", "application/pdf")},
            )

            self.assertEqual(response.status_code, 200)
            self.assertIn("已保存檔案", response.text)
            self.assertIn("尚未支援文字抽取", response.text)

    def _client_for(self, workspace: Path) -> TestClient:
        patcher = patch.dict(os.environ, {"CV_BUILDER_WORKSPACE": str(workspace)})
        patcher.start()
        self.addCleanup(patcher.stop)
        return TestClient(create_app())


if __name__ == "__main__":
    unittest.main()

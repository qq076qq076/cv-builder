import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.schemas.evidence import EvidenceSource
from app.storage.evidence import EvidenceRepository
from app.storage.workspace import ensure_workspace_dirs
from app.main import create_app
from tests.test_pdf_importer import SIMPLE_TEXT_PDF


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
                files={"resume_file": ("resume.pdf", SIMPLE_TEXT_PDF, "application/pdf")},
            )

            self.assertEqual(response.status_code, 200)
            self.assertIn("已保存檔案", response.text)
            self.assertIn("文字預覽", response.text)
            self.assertIn("Hello PDF Resume", response.text)

    def test_duplicate_upload_reuses_existing_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            ensure_workspace_dirs(workspace)
            client = self._client_for(workspace)

            first_response = client.post(
                "/import/files",
                files={"resume_file": ("resume.txt", b"same", "text/plain")},
            )
            second_response = client.post(
                "/import/files",
                files={"resume_file": ("copy.txt", b"same", "text/plain")},
            )

            self.assertEqual(first_response.status_code, 200)
            self.assertEqual(second_response.status_code, 200)
            self.assertIn("內容已存在", second_response.text)
            self.assertEqual(len(list((workspace / "evidence/files").iterdir())), 1)
            self.assertEqual(len(list((workspace / "evidence/extracted").iterdir())), 1)

    def test_import_page_lists_existing_sources_with_reprocess_button(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            source = self._create_legacy_pdf_source(workspace)

            response = self._client_for(workspace).get("/import")

            self.assertEqual(response.status_code, 200)
            self.assertIn(source.id, response.text)
            self.assertIn("重新抽取", response.text)

    def test_reprocess_source_route_updates_existing_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            source = self._create_legacy_pdf_source(workspace)

            response = self._client_for(workspace).post(
                f"/import/sources/{source.id}/reprocess",
            )

            self.assertEqual(response.status_code, 200)
            self.assertIn("已重新處理來源", response.text)
            self.assertIn("Hello PDF Resume", response.text)

            updated_source = EvidenceRepository(workspace).get_source(source.id)
            self.assertEqual(updated_source.extraction_status, "completed")
            self.assertIsNotNone(updated_source.content_hash)

    def _client_for(self, workspace: Path) -> TestClient:
        patcher = patch.dict(os.environ, {"CV_BUILDER_WORKSPACE": str(workspace)})
        patcher.start()
        self.addCleanup(patcher.stop)
        return TestClient(create_app())

    def _create_legacy_pdf_source(self, workspace: Path) -> EvidenceSource:
        ensure_workspace_dirs(workspace)
        path = workspace / "evidence/files/src_old_resume.pdf"
        path.write_bytes(SIMPLE_TEXT_PDF)
        source = EvidenceSource(
            id="src_old",
            label="old resume",
            path="evidence/files/src_old_resume.pdf",
            originalFilename="old.pdf",
            contentType="application/pdf",
            sizeBytes=len(SIMPLE_TEXT_PDF),
            createdAt=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
        EvidenceRepository(workspace).add_source(source)
        return source


if __name__ == "__main__":
    unittest.main()

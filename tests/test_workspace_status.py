import json
import tempfile
import unittest
from pathlib import Path

from app.schemas.workspace import WorkspaceStatus
from app.storage.workspace import get_workspace_status


class WorkspaceStatusTest(unittest.TestCase):
    def test_missing_workspace_returns_no_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"

            self.assertEqual(get_workspace_status(workspace), WorkspaceStatus.NO_WORKSPACE)

    def test_empty_workspace_returns_empty_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()

            self.assertEqual(get_workspace_status(workspace), WorkspaceStatus.EMPTY_WORKSPACE)

    def test_career_profile_returns_has_career_data(self) -> None:
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

            self.assertEqual(get_workspace_status(workspace), WorkspaceStatus.HAS_CAREER_DATA)

    def test_generated_output_returns_has_generated_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            outputs = workspace / "outputs"
            outputs.mkdir(parents=True)
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
            (outputs / "resume.md").write_text("# Resume\n", encoding="utf-8")

            self.assertEqual(get_workspace_status(workspace), WorkspaceStatus.HAS_GENERATED_OUTPUTS)

    def test_invalid_career_json_returns_empty_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()
            (workspace / "career.json").write_text("{", encoding="utf-8")

            self.assertEqual(get_workspace_status(workspace), WorkspaceStatus.EMPTY_WORKSPACE)

    def _write_json(self, path: Path, data: dict) -> None:
        path.write_text(json.dumps(data), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()


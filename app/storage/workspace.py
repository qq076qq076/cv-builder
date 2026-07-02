from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.schemas.workspace import WorkspaceStatus


CAREER_FILE = "career.json"
EVIDENCE_SOURCES_FILE = "evidence/sources.json"
OUTPUT_SUFFIXES = {".json", ".md", ".html", ".pdf", ".docx"}


def get_workspace_status(workspace_path: Path) -> WorkspaceStatus:
    if not workspace_path.exists() or not workspace_path.is_dir():
        return WorkspaceStatus.NO_WORKSPACE

    career_data = _read_json(workspace_path / CAREER_FILE)
    has_career_data = _has_meaningful_career_data(career_data)

    if has_career_data and _has_generated_outputs(workspace_path):
        return WorkspaceStatus.HAS_GENERATED_OUTPUTS

    if has_career_data:
        return WorkspaceStatus.HAS_CAREER_DATA

    return WorkspaceStatus.EMPTY_WORKSPACE


def ensure_workspace_dirs(workspace_path: Path) -> None:
    for relative_path in ("evidence/files", "jobs", "outputs", "versions"):
        (workspace_path / relative_path).mkdir(parents=True, exist_ok=True)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    return data if isinstance(data, dict) else None


def _has_meaningful_career_data(data: dict[str, Any] | None) -> bool:
    if not data or data.get("schemaVersion") is None:
        return False

    profile = data.get("profile")
    if isinstance(profile, dict) and any(_has_value(value) for value in profile.values()):
        return True

    for key in ("experiences", "projects", "skills", "education", "certificates", "languages"):
        value = data.get(key)
        if isinstance(value, list) and len(value) > 0:
            return True

    return False


def _has_generated_outputs(workspace_path: Path) -> bool:
    output_dir = workspace_path / "outputs"
    if not output_dir.exists() or not output_dir.is_dir():
        return False

    return any(path.is_file() and path.suffix in OUTPUT_SUFFIXES for path in output_dir.iterdir())


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) > 0
    return True

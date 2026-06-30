from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.schemas.workspace import WorkspaceStatus
from app.storage.workspace import get_workspace_status


@dataclass(frozen=True)
class DashboardState:
    workspace_path: Path
    status: WorkspaceStatus


class DashboardService:
    def __init__(self, workspace_path: Path) -> None:
        self.workspace_path = workspace_path

    def get_state(self) -> DashboardState:
        return DashboardState(
            workspace_path=self.workspace_path,
            status=get_workspace_status(self.workspace_path),
        )


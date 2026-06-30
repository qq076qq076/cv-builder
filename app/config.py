from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    workspace_path: Path
    openai_model: str


def get_settings() -> Settings:
    return Settings(
        workspace_path=Path(os.getenv("CV_BUILDER_WORKSPACE", "./workspace")),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
    )


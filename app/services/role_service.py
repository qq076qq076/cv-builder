from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from app.schemas.role import RoleMetadata, RoleProfile
from app.storage.atomic import atomic_write_json
from app.storage.workspace import ensure_workspace_dirs

LEGACY_WORKSPACE_DIRS = {"evidence", "jobs", "outputs", "versions"}


class RoleService:
    def __init__(self, workspace_path: Path) -> None:
        self.workspace_path = workspace_path

    def list_roles(self) -> list[RoleMetadata]:
        if not self.workspace_path.is_dir():
            return []

        roles = []
        for path in sorted(self.workspace_path.iterdir()):
            if not path.is_dir() or path.name in LEGACY_WORKSPACE_DIRS:
                continue
            metadata = self.get_role(path.name)
            if metadata is not None:
                roles.append(metadata)

        return roles

    def get_role(self, role_id: str) -> RoleMetadata | None:
        role_path = self.role_path(role_id)
        metadata_path = role_path / "metadata.json"

        if metadata_path.is_file():
            try:
                data = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
            return RoleMetadata.model_validate(data)

        if role_path.is_dir() and role_id not in LEGACY_WORKSPACE_DIRS:
            metadata = RoleMetadata(
                id=role_id,
                name=role_id,
                createdAt=datetime.now(timezone.utc),
            )
            atomic_write_json(metadata_path, metadata.model_dump(mode="json", by_alias=True))
            return metadata

        return None

    def create_role(self, name: str) -> RoleMetadata:
        self.workspace_path.mkdir(parents=True, exist_ok=True)

        role_id = self._unique_role_id(_slugify(name))
        role_path = self.role_path(role_id)
        ensure_workspace_dirs(role_path)

        metadata = RoleMetadata(
            id=role_id,
            name=name.strip() or role_id,
            createdAt=datetime.now(timezone.utc),
        )
        atomic_write_json(role_path / "metadata.json", metadata.model_dump(mode="json", by_alias=True))
        self.save_profile(role_id, RoleProfile(name=metadata.name))
        return metadata

    def role_path(self, role_id: str) -> Path:
        return self.workspace_path / role_id

    def load_profile(self, role_id: str) -> RoleProfile:
        profile_path = self.role_path(role_id) / "evidence/profile.json"
        if not profile_path.is_file():
            return RoleProfile()

        try:
            data = json.loads(profile_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return RoleProfile()

        return RoleProfile.model_validate(data)

    def save_profile(self, role_id: str, profile: RoleProfile) -> RoleProfile:
        updated_profile = profile.model_copy(update={"updated_at": datetime.now(timezone.utc)})
        atomic_write_json(
            self.role_path(role_id) / "evidence/profile.json",
            updated_profile.model_dump(mode="json", by_alias=True),
        )
        return updated_profile

    def _unique_role_id(self, base_role_id: str) -> str:
        role_id = base_role_id or "role"
        candidate = role_id
        index = 2
        while self.role_path(candidate).exists() or candidate in LEGACY_WORKSPACE_DIRS:
            candidate = f"{role_id}-{index}"
            index += 1
        return candidate


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip().lower())
    normalized = normalized.strip(".-")
    return normalized or "role"


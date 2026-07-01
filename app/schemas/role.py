from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RoleMetadata(BaseModel):
    schema_version: int = Field(default=1, alias="schemaVersion")
    id: str
    name: str
    created_at: datetime = Field(alias="createdAt")

    model_config = {"populate_by_name": True}


class RoleProfile(BaseModel):
    schema_version: int = Field(default=1, alias="schemaVersion")
    name: str = ""
    skills: str = ""
    career: str = ""
    autobiography: str = ""
    updated_at: datetime | None = Field(default=None, alias="updatedAt")

    model_config = {"populate_by_name": True}


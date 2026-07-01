from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TrackedJob(BaseModel):
    schema_version: int = Field(default=1, alias="schemaVersion")
    id: str
    title: str = ""
    company: str = ""
    url: str = ""
    description: str = ""
    status: str = "tracking"
    created_at: datetime = Field(alias="createdAt")

    model_config = {"populate_by_name": True}


class TrackedJobCollection(BaseModel):
    schema_version: int = Field(default=1, alias="schemaVersion")
    jobs: list[TrackedJob] = Field(default_factory=list)

    model_config = {"populate_by_name": True}

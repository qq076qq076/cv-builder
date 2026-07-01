from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class EvidenceSource(BaseModel):
    id: str
    type: str = "uploaded_file"
    label: str
    path: str
    original_filename: str = Field(alias="originalFilename")
    content_type: str | None = Field(default=None, alias="contentType")
    size_bytes: int = Field(alias="sizeBytes")
    created_at: datetime = Field(alias="createdAt")

    model_config = {"populate_by_name": True}


class EvidenceSourceCollection(BaseModel):
    schema_version: int = Field(default=1, alias="schemaVersion")
    sources: list[EvidenceSource] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


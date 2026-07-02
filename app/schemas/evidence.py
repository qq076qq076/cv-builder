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
    source_url: str | None = Field(default=None, alias="sourceUrl")
    size_bytes: int = Field(alias="sizeBytes")
    content_hash: str | None = Field(default=None, alias="contentHash")
    extracted_text_path: str | None = Field(default=None, alias="extractedTextPath")
    extraction_status: str = Field(default="not_supported", alias="extractionStatus")
    created_at: datetime = Field(alias="createdAt")

    model_config = {"populate_by_name": True}


class EvidenceSourceCollection(BaseModel):
    schema_version: int = Field(default=1, alias="schemaVersion")
    sources: list[EvidenceSource] = Field(default_factory=list)

    model_config = {"populate_by_name": True}

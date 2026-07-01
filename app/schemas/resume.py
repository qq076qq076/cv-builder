from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ResumeContact(BaseModel):
    email: str = ""
    phone: str = ""
    location: str = ""
    links: list[str] = Field(default_factory=list)


class ResumeExperience(BaseModel):
    company: str = ""
    title: str = ""
    start_date: str = Field(default="", alias="startDate")
    end_date: str = Field(default="", alias="endDate")
    summary: str = ""
    achievements: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class ResumeProject(BaseModel):
    name: str = ""
    role: str = ""
    description: str = ""
    technologies: list[str] = Field(default_factory=list)
    outcomes: list[str] = Field(default_factory=list)


class ResumeEducation(BaseModel):
    school: str = ""
    degree: str = ""
    major: str = ""
    start_date: str = Field(default="", alias="startDate")
    end_date: str = Field(default="", alias="endDate")

    model_config = {"populate_by_name": True}


class ResumeCertificate(BaseModel):
    name: str = ""
    issuer: str = ""
    date: str = ""


class ResumeLanguage(BaseModel):
    name: str = ""
    proficiency: str = ""


class NormalizedResume(BaseModel):
    schema_version: int = Field(default=1, alias="schemaVersion")
    source_ids: list[str] = Field(default_factory=list, alias="sourceIds")
    name: str = ""
    title: str = ""
    summary: str = ""
    autobiography: str = ""
    contact: ResumeContact = Field(default_factory=ResumeContact)
    skills: list[str] = Field(default_factory=list)
    experiences: list[ResumeExperience] = Field(default_factory=list)
    projects: list[ResumeProject] = Field(default_factory=list)
    education: list[ResumeEducation] = Field(default_factory=list)
    certificates: list[ResumeCertificate] = Field(default_factory=list)
    languages: list[ResumeLanguage] = Field(default_factory=list)
    updated_at: datetime | None = Field(default=None, alias="updatedAt")

    model_config = {"populate_by_name": True}

    def has_content(self) -> bool:
        return any(
            [
                self.name.strip(),
                self.title.strip(),
                self.summary.strip(),
                self.autobiography.strip(),
                self.skills,
                self.experiences,
                self.projects,
                self.education,
                self.certificates,
                self.languages,
            ]
        )


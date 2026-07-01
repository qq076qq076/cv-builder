from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ResumeContact(BaseModel):
    email: str = Field(default="", description="Email address found in the resume.")
    phone: str = Field(default="", description="Phone number found in the resume.")
    location: str = Field(default="", description="Candidate location, city, country, or region.")
    links: list[str] = Field(
        default_factory=list,
        description="URLs such as portfolio, GitHub, LinkedIn, project links, or personal sites.",
    )


class ResumeExperience(BaseModel):
    company: str = Field(default="", description="Company or organization name.")
    title: str = Field(default="", description="Job title or role title.")
    start_date: str = Field(
        default="",
        alias="startDate",
        description="Start date exactly as shown, for example 'Sep. 2022'.",
    )
    end_date: str = Field(
        default="",
        alias="endDate",
        description="End date exactly as shown, or 'Present' if current.",
    )
    summary: str = Field(
        default="",
        description="Concise summary of responsibilities for this role.",
    )
    achievements: list[str] = Field(
        default_factory=list,
        description=(
            "Bullet achievements, impact metrics, leadership, delivery, testing, CI/CD, "
            "performance, or process improvements."
        ),
    )
    technologies: list[str] = Field(
        default_factory=list,
        description="Technologies, frameworks, tools, platforms, and languages used in this role.",
    )

    model_config = {"populate_by_name": True}


class ResumeProject(BaseModel):
    name: str = Field(default="", description="Project or product name.")
    role: str = Field(default="", description="Candidate role in the project if present.")
    description: str = Field(
        default="",
        description="What the project does and its business or technical purpose.",
    )
    technologies: list[str] = Field(
        default_factory=list,
        description="Technologies mentioned for this project.",
    )
    outcomes: list[str] = Field(
        default_factory=list,
        description="Notable project outcomes, features, links, or impact.",
    )


class ResumeEducation(BaseModel):
    school: str = Field(default="", description="School or university name.")
    degree: str = Field(default="", description="Degree type if present.")
    major: str = Field(default="", description="Major, department, or field of study.")
    start_date: str = Field(
        default="",
        alias="startDate",
        description="Education start date if present.",
    )
    end_date: str = Field(
        default="",
        alias="endDate",
        description="Education end date or graduation date if present.",
    )

    model_config = {"populate_by_name": True}


class ResumeCertificate(BaseModel):
    name: str = Field(default="", description="Certificate name.")
    issuer: str = Field(default="", description="Issuing organization.")
    date: str = Field(default="", description="Certificate date if present.")


class ResumeLanguage(BaseModel):
    name: str = Field(default="", description="Language name.")
    proficiency: str = Field(
        default="",
        description=(
            "Language proficiency exactly as shown, for example "
            "'Native' or 'Intermediate'."
        ),
    )


class NormalizedResume(BaseModel):
    schema_version: int = Field(
        default=1,
        alias="schemaVersion",
        description="Schema version. Always return 1.",
    )
    source_ids: list[str] = Field(
        default_factory=list,
        alias="sourceIds",
        description="Source IDs used to build this resume. Include the provided source ID.",
    )
    name: str = Field(default="", description="Candidate full name.")
    title: str = Field(
        default="",
        description="Current or target professional title from the resume header.",
    )
    summary: str = Field(
        default="",
        description=(
            "Resume professional summary. If a summary paragraph exists near the top, "
            "preserve it concisely."
        ),
    )
    autobiography: str = Field(
        default="",
        description=(
            "Autobiography or personal statement if explicitly present. "
            "Leave empty if not present."
        ),
    )
    contact: ResumeContact = Field(
        default_factory=ResumeContact,
        description="Contact information extracted from the resume header or contact section.",
    )
    skills: list[str] = Field(
        default_factory=list,
        description=(
            "All explicit skills grouped or listed in the resume. Include frontend, backend, "
            "tools, languages, testing, DevOps, AI tools, and design tools."
        ),
    )
    experiences: list[ResumeExperience] = Field(
        default_factory=list,
        description="Every work experience entry in reverse chronological order if present.",
    )
    projects: list[ResumeProject] = Field(
        default_factory=list,
        description="Every project entry in the Projects section if present.",
    )
    education: list[ResumeEducation] = Field(
        default_factory=list,
        description="Every education entry if present.",
    )
    certificates: list[ResumeCertificate] = Field(
        default_factory=list,
        description="Every certificate entry if present.",
    )
    languages: list[ResumeLanguage] = Field(
        default_factory=list,
        description="Human languages and proficiency levels from the resume.",
    )
    updated_at: datetime | None = Field(
        default=None,
        alias="updatedAt",
        description="Leave null; the application fills this value.",
    )

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

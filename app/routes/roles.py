from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, File, Form, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.ai.cover_letter_generator import (
    CoverLetterGenerator,
    GeminiCoverLetterGenerator,
    OpenAICoverLetterGenerator,
)
from app.config import get_settings
from app.schemas.role import RoleProfile
from app.schemas.resume import (
    ResumeCertificate,
    ResumeContact,
    ResumeEducation,
    ResumeExperience,
    ResumeLanguage,
    ResumeProject,
)
from app.services.job_service import JobService
from app.services.import_service import ImportService
from app.services.role_service import RoleService
from app.services.resume_normalization_service import (
    ResumeNormalizationResult,
    ResumeNormalizationService,
)
from app.storage.evidence import EvidenceRepository
from app.storage.resume import ResumeRepository

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.post("/roles")
def create_role(role_name: str = Form(...)) -> RedirectResponse:
    settings = get_settings()
    role = RoleService(settings.workspace_path).create_role(role_name)
    return RedirectResponse(f"/roles/{role.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/roles/{role_id}", response_class=HTMLResponse)
def role_detail(
    request: Request,
    role_id: str,
    generated_output: str | None = None,
    generated_error: str | None = None,
) -> HTMLResponse:
    settings = get_settings()
    role_service = RoleService(settings.workspace_path)
    role = role_service.get_role(role_id)
    if role is None:
        return templates.TemplateResponse(
            request,
            "role_not_found.html",
            context={"request": request, "role_id": role_id},
            status_code=404,
        )

    role_path = role_service.role_path(role_id)
    profile = role_service.load_profile(role_id)
    resume = ResumeRepository(role_path).load()
    job_service = JobService(role_path)
    active_generated_output = (
        job_service.get_output_by_path(generated_output) if generated_output else None
    )
    return templates.TemplateResponse(
        request,
        "role_detail.html",
        context={
            "request": request,
            "role": role,
            "profile": profile,
            "resume": resume,
            "has_role_content": _has_profile_content(profile) or resume.has_content(),
            "sources": EvidenceRepository(role_path).list_sources().sources,
            "jobs": job_service.list_jobs(),
            "job_outputs": job_service.list_outputs_by_job(),
            "generated_output": generated_output,
            "generated_error": generated_error,
            "active_generated_output": active_generated_output,
            "normalization_result": None,
            "edit": _resume_edit_context(resume),
        },
    )


@router.post("/roles/{role_id}/profile")
def update_role_profile(
    role_id: str,
    name: str = Form(""),
    skills: str = Form(""),
    career: str = Form(""),
    autobiography: str = Form(""),
) -> RedirectResponse:
    settings = get_settings()
    role_service = RoleService(settings.workspace_path)
    role_service.save_profile(
        role_id,
        RoleProfile(
            name=name,
            skills=skills,
            career=career,
            autobiography=autobiography,
        ),
    )
    return RedirectResponse(f"/roles/{role_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/roles/{role_id}/initialize", response_class=HTMLResponse)
async def initialize_role_sources(
    request: Request,
    role_id: str,
    resume_file: UploadFile | None = File(default=None),
    source_url: list[str] = Form(default=[]),
) -> HTMLResponse:
    settings = get_settings()
    role_service = RoleService(settings.workspace_path)
    role = role_service.get_role(role_id)
    if role is None:
        return templates.TemplateResponse(
            request,
            "role_not_found.html",
            context={"request": request, "role_id": role_id},
            status_code=404,
        )

    role_path = role_service.role_path(role_id)
    source_ids = await _save_submitted_sources(
        role_path=role_path,
        resume_file=resume_file,
        source_url=source_url,
    )

    if not source_ids:
        result = ResumeNormalizationResult(status="not_found", message="請至少提供一個檔案或網址")
        return _render_role_detail(
            request=request,
            role=role,
            role_id=role_id,
            role_path=role_path,
            role_service=role_service,
            normalization_result=result,
        )

    result = ResumeNormalizationService(
        role_path=role_path,
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        gemini_api_key=settings.gemini_api_key,
        gemini_model=settings.gemini_model,
    ).normalize_sources(source_ids)
    if result.status == "completed" and result.resume is not None:
        role_service.sync_profile_from_resume(role_id, result.resume)
        result = ResumeNormalizationResult(
            status="completed",
            resume=result.resume,
            message=f"已整合 {len(source_ids)} 筆來源並完成初始化。",
        )

    return _render_role_detail(
        request=request,
        role=role,
        role_id=role_id,
        role_path=role_path,
        role_service=role_service,
        normalization_result=result,
    )


@router.post("/roles/{role_id}/sources", response_class=HTMLResponse)
async def update_role_sources(
    request: Request,
    role_id: str,
    resume_file: UploadFile | None = File(default=None),
    source_url: list[str] = Form(default=[]),
) -> HTMLResponse:
    settings = get_settings()
    role_service = RoleService(settings.workspace_path)
    role = role_service.get_role(role_id)
    if role is None:
        return templates.TemplateResponse(
            request,
            "role_not_found.html",
            context={"request": request, "role_id": role_id},
            status_code=404,
        )

    role_path = role_service.role_path(role_id)
    saved_source_ids = await _save_submitted_sources(
        role_path=role_path,
        resume_file=resume_file,
        source_url=source_url,
    )
    message = (
        f"已更新 {len(saved_source_ids)} 筆來源。"
        if saved_source_ids
        else "請至少提供一個檔案或網址"
    )
    result = ResumeNormalizationResult(
        status="completed" if saved_source_ids else "not_found",
        message=message,
    )
    return _render_role_detail(
        request=request,
        role=role,
        role_id=role_id,
        role_path=role_path,
        role_service=role_service,
        normalization_result=result,
    )


@router.post("/roles/{role_id}/resume/profile")
def update_resume_profile(
    role_id: str,
    name: str = Form(""),
    title: str = Form(""),
    summary: str = Form(""),
    autobiography: str = Form(""),
) -> RedirectResponse:
    repository = _resume_repository_for_role(role_id)
    resume = repository.load()
    repository.save(
        resume.model_copy(
            update={
                "name": name,
                "title": title,
                "summary": summary,
                "autobiography": autobiography,
            }
        )
    )
    return RedirectResponse(f"/roles/{role_id}#profile", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/roles/{role_id}/resume/skills")
def update_resume_skills(
    role_id: str,
    skills: str = Form(""),
    skill_items: list[str] = Form(default=[]),
) -> RedirectResponse:
    repository = _resume_repository_for_role(role_id)
    resume = repository.load()
    parsed_skills = _clean_list(skill_items) if skill_items else _split_lines(skills)
    repository.save(resume.model_copy(update={"skills": parsed_skills}))
    return RedirectResponse(f"/roles/{role_id}#skills", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/roles/{role_id}/resume/contact")
def update_resume_contact(
    role_id: str,
    email: str = Form(""),
    phone: str = Form(""),
    location: str = Form(""),
    links: str = Form(""),
) -> RedirectResponse:
    repository = _resume_repository_for_role(role_id)
    resume = repository.load()
    repository.save(
        resume.model_copy(
            update={
                "contact": ResumeContact(
                    email=email,
                    phone=phone,
                    location=location,
                    links=_split_lines(links),
                )
            }
        )
    )
    return RedirectResponse(f"/roles/{role_id}#contact", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/roles/{role_id}/resume/experiences")
def update_resume_experiences(
    role_id: str,
    experiences: str = Form(""),
    experience_title: list[str] = Form(default=[]),
    experience_company: list[str] = Form(default=[]),
    experience_period: list[str] = Form(default=[]),
    experience_summary: list[str] = Form(default=[]),
    experience_achievements: list[str] = Form(default=[]),
    experience_technologies: list[str] = Form(default=[]),
) -> RedirectResponse:
    repository = _resume_repository_for_role(role_id)
    resume = repository.load()
    parsed_experiences = (
        _parse_experience_items(
            titles=experience_title,
            companies=experience_company,
            periods=experience_period,
            summaries=experience_summary,
            achievements=experience_achievements,
            technologies=experience_technologies,
        )
        if experience_title
        else _parse_experience_blocks(experiences)
    )
    repository.save(
        resume.model_copy(update={"experiences": parsed_experiences})
    )
    return RedirectResponse(f"/roles/{role_id}#experiences", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/roles/{role_id}/resume/education")
def update_resume_education(
    role_id: str,
    education: str = Form(""),
    certificates: str = Form(""),
    education_school: list[str] = Form(default=[]),
    education_degree: list[str] = Form(default=[]),
    education_major: list[str] = Form(default=[]),
    education_period: list[str] = Form(default=[]),
    certificate_name: list[str] = Form(default=[]),
    certificate_issuer: list[str] = Form(default=[]),
    certificate_date: list[str] = Form(default=[]),
) -> RedirectResponse:
    repository = _resume_repository_for_role(role_id)
    resume = repository.load()
    parsed_education = (
        _parse_education_items(
            schools=education_school,
            degrees=education_degree,
            majors=education_major,
            periods=education_period,
        )
        if education_school
        else _parse_education_lines(education)
    )
    parsed_certificates = (
        _parse_certificate_items(
            names=certificate_name,
            issuers=certificate_issuer,
            dates=certificate_date,
        )
        if certificate_name
        else _parse_certificate_lines(certificates)
    )
    repository.save(
        resume.model_copy(
            update={
                "education": parsed_education,
                "certificates": parsed_certificates,
            }
        )
    )
    return RedirectResponse(f"/roles/{role_id}#education", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/roles/{role_id}/resume/projects")
def update_resume_projects(
    role_id: str,
    projects: str = Form(""),
    project_name: list[str] = Form(default=[]),
    project_role: list[str] = Form(default=[]),
    project_description: list[str] = Form(default=[]),
    project_technologies: list[str] = Form(default=[]),
    project_outcomes: list[str] = Form(default=[]),
) -> RedirectResponse:
    repository = _resume_repository_for_role(role_id)
    resume = repository.load()
    parsed_projects = (
        _parse_project_items(
            names=project_name,
            roles=project_role,
            descriptions=project_description,
            technologies=project_technologies,
            outcomes=project_outcomes,
        )
        if project_name
        else _parse_project_blocks(projects)
    )
    repository.save(resume.model_copy(update={"projects": parsed_projects}))
    return RedirectResponse(f"/roles/{role_id}#projects", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/roles/{role_id}/resume/languages")
def update_resume_languages(
    role_id: str,
    languages: str = Form(""),
    language_name: list[str] = Form(default=[]),
    language_proficiency: list[str] = Form(default=[]),
) -> RedirectResponse:
    repository = _resume_repository_for_role(role_id)
    resume = repository.load()
    parsed_languages = (
        _parse_language_items(language_name, language_proficiency)
        if language_name
        else _parse_language_lines(languages)
    )
    repository.save(resume.model_copy(update={"languages": parsed_languages}))
    return RedirectResponse(f"/roles/{role_id}#languages", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/roles/{role_id}/jobs")
def create_role_job(role_id: str, job_url: str = Form(...)) -> RedirectResponse:
    settings = get_settings()
    role_service = RoleService(settings.workspace_path)
    role = role_service.get_role(role_id)
    if role is not None:
        JobService(role_service.role_path(role_id)).create_job_from_url(job_url)
    return RedirectResponse(f"/roles/{role_id}#jobs", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/roles/{role_id}/jobs/{job_id}/generate")
def generate_role_job_output(
    role_id: str,
    job_id: str,
    kind: str = Form(...),
) -> RedirectResponse:
    settings = get_settings()
    role_service = RoleService(settings.workspace_path)
    role = role_service.get_role(role_id)
    if role is not None:
        role_path = role_service.role_path(role_id)
        try:
            generated_output = JobService(role_path).generate_output(
                job_id=job_id,
                kind=kind,
                resume=ResumeRepository(role_path).load(),
                cover_letter_generator=_build_cover_letter_generator(
                    role_path=role_path,
                    settings=settings,
                    kind=kind,
                ),
            )
        except RuntimeError as exc:
            return RedirectResponse(
                f"/roles/{role_id}?generated_error={quote(str(exc))}#jobs",
                status_code=status.HTTP_303_SEE_OTHER,
            )
        if generated_output is not None:
            return RedirectResponse(
                f"/roles/{role_id}?generated_output={generated_output.path}#jobs",
                status_code=status.HTTP_303_SEE_OTHER,
            )
    return RedirectResponse(f"/roles/{role_id}#jobs", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/roles/{role_id}/sources/{source_id}/normalize", response_class=HTMLResponse)
def normalize_source(request: Request, role_id: str, source_id: str) -> HTMLResponse:
    settings = get_settings()
    role_service = RoleService(settings.workspace_path)
    role = role_service.get_role(role_id)
    if role is None:
        return templates.TemplateResponse(
            request,
            "role_not_found.html",
            context={"request": request, "role_id": role_id},
            status_code=404,
        )

    role_path = role_service.role_path(role_id)
    result = ResumeNormalizationService(
        role_path=role_path,
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        gemini_api_key=settings.gemini_api_key,
        gemini_model=settings.gemini_model,
    ).normalize_source(source_id)
    if result.status == "completed" and result.resume is not None:
        role_service.sync_profile_from_resume(role_id, result.resume)
    return _render_role_detail(
        request=request,
        role=role,
        role_id=role_id,
        role_path=role_path,
        role_service=role_service,
        normalization_result=result,
    )


@router.post("/roles/{role_id}/sources/normalize", response_class=HTMLResponse)
def normalize_all_sources(request: Request, role_id: str) -> HTMLResponse:
    settings = get_settings()
    role_service = RoleService(settings.workspace_path)
    role = role_service.get_role(role_id)
    if role is None:
        return templates.TemplateResponse(
            request,
            "role_not_found.html",
            context={"request": request, "role_id": role_id},
            status_code=404,
        )

    role_path = role_service.role_path(role_id)
    sources = EvidenceRepository(role_path).list_sources().sources
    if not sources:
        result = ResumeNormalizationResult(status="not_found", message="目前沒有可解析的來源")
        return _render_role_detail(
            request=request,
            role=role,
            role_id=role_id,
            role_path=role_path,
            role_service=role_service,
            normalization_result=result,
        )

    service = ResumeNormalizationService(
        role_path=role_path,
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        gemini_api_key=settings.gemini_api_key,
        gemini_model=settings.gemini_model,
    )
    result = service.normalize_sources([source.id for source in sources])
    if result.status == "completed" and result.resume is not None:
        role_service.sync_profile_from_resume(role_id, result.resume)
        result = ResumeNormalizationResult(
            status="completed",
            resume=result.resume,
            message=f"已整合 {len(sources)} 筆 Evidence 來源。",
        )

    return _render_role_detail(
        request=request,
        role=role,
        role_id=role_id,
        role_path=role_path,
        role_service=role_service,
        normalization_result=result,
    )


def _render_role_detail(
    *,
    request: Request,
    role,
    role_id: str,
    role_path,
    role_service: RoleService,
    normalization_result,
) -> HTMLResponse:
    profile = role_service.load_profile(role_id)
    resume = ResumeRepository(role_path).load()
    job_service = JobService(role_path)
    return templates.TemplateResponse(
        request,
        "role_detail.html",
        context={
            "request": request,
            "role": role,
            "profile": profile,
            "resume": resume,
            "has_role_content": _has_profile_content(profile) or resume.has_content(),
            "sources": EvidenceRepository(role_path).list_sources().sources,
            "jobs": job_service.list_jobs(),
            "job_outputs": job_service.list_outputs_by_job(),
            "generated_output": None,
            "generated_error": None,
            "active_generated_output": None,
            "normalization_result": normalization_result,
            "edit": _resume_edit_context(resume),
        },
    )


def _build_cover_letter_generator(
    *,
    role_path,
    settings,
    kind: str,
) -> CoverLetterGenerator | None:
    if kind != "cover_letter":
        return None
    if settings.openai_api_key:
        return OpenAICoverLetterGenerator(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            log_path=role_path / "logs/ai-cover-letter.jsonl",
        )
    if settings.gemini_api_key:
        return GeminiCoverLetterGenerator(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            log_path=role_path / "logs/ai-cover-letter.jsonl",
        )
    raise RuntimeError("缺少 OPENAI_API_KEY 或 GEMINI_API_KEY，無法生成推薦信")


def _has_profile_content(profile: RoleProfile) -> bool:
    return any(
        [
            profile.name.strip(),
            profile.skills.strip(),
            profile.career.strip(),
            profile.autobiography.strip(),
        ]
    )


def _resume_repository_for_role(role_id: str) -> ResumeRepository:
    settings = get_settings()
    role_service = RoleService(settings.workspace_path)
    return ResumeRepository(role_service.role_path(role_id))


async def _save_submitted_sources(
    *,
    role_path,
    resume_file: UploadFile | None,
    source_url: list[str],
) -> list[str]:
    import_service = ImportService(role_path)
    source_ids = []

    if resume_file is not None and resume_file.filename:
        saved_upload = import_service.save_uploaded_file(
            filename=resume_file.filename,
            content_type=resume_file.content_type,
            content=await resume_file.read(),
        )
        source_ids.append(saved_upload.source.id)

    for url in _clean_list(source_url):
        saved_url = import_service.save_url_source(url=url)
        source_ids.append(saved_url.source.id)

    return source_ids


def _split_lines(value: str) -> list[str]:
    return [line.strip() for line in value.replace(",", "\n").splitlines() if line.strip()]


def _clean_list(values: list[str]) -> list[str]:
    return [value.strip() for value in values if value.strip()]


def _parallel_value(values: list[str], index: int) -> str:
    return values[index].strip() if index < len(values) else ""


def _split_blocks(value: str) -> list[str]:
    normalized = value.replace("\r\n", "\n").strip()
    if not normalized:
        return []
    return [block.strip() for block in normalized.split("\n---\n") if block.strip()]


def _parse_kv_block(block: str) -> dict[str, str]:
    data: dict[str, str] = {}
    current_key = ""
    for line in block.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            current_key = key.strip().lower()
            data[current_key] = value.strip()
        elif current_key:
            data[current_key] = f"{data[current_key]}\n{line.strip()}".strip()
    return data


def _parse_csv(value: str) -> list[str]:
    normalized = value.replace("\n", ",")
    return [item.strip() for item in normalized.split(",") if item.strip()]


def _parse_period(value: str) -> tuple[str, str]:
    for separator in (" - ", " – ", " — ", "|"):
        if separator in value:
            start_date, end_date = value.split(separator, 1)
            return start_date.strip(), end_date.strip()
    return value.strip(), ""


def _parse_experience_blocks(value: str) -> list[ResumeExperience]:
    experiences = []
    for block in _split_blocks(value):
        data = _parse_kv_block(block)
        start_date, end_date = _parse_period(data.get("period", ""))
        experiences.append(
            ResumeExperience(
                company=data.get("company", ""),
                title=data.get("title", ""),
                startDate=start_date,
                endDate=end_date,
                summary=data.get("summary", ""),
                achievements=_parse_csv(data.get("achievements", "")),
                technologies=_parse_csv(data.get("technologies", "")),
            )
        )
    return experiences


def _parse_experience_items(
    titles: list[str],
    companies: list[str],
    periods: list[str],
    summaries: list[str],
    achievements: list[str],
    technologies: list[str],
) -> list[ResumeExperience]:
    experiences = []
    for index, title in enumerate(titles):
        if not title.strip():
            continue
        start_date, end_date = _parse_period(_parallel_value(periods, index))
        experiences.append(
            ResumeExperience(
                title=title.strip(),
                company=_parallel_value(companies, index),
                startDate=start_date,
                endDate=end_date,
                summary=_parallel_value(summaries, index),
                achievements=_parse_csv(_parallel_value(achievements, index)),
                technologies=_parse_csv(_parallel_value(technologies, index)),
            )
        )
    return experiences


def _parse_project_blocks(value: str) -> list[ResumeProject]:
    projects = []
    for block in _split_blocks(value):
        data = _parse_kv_block(block)
        projects.append(
            ResumeProject(
                name=data.get("name", ""),
                role=data.get("role", ""),
                description=data.get("description", ""),
                technologies=_parse_csv(data.get("technologies", "")),
                outcomes=_parse_csv(data.get("outcomes", "")),
            )
        )
    return projects


def _parse_project_items(
    names: list[str],
    roles: list[str],
    descriptions: list[str],
    technologies: list[str],
    outcomes: list[str],
) -> list[ResumeProject]:
    projects = []
    for index, name in enumerate(names):
        if not name.strip():
            continue
        projects.append(
            ResumeProject(
                name=name.strip(),
                role=_parallel_value(roles, index),
                description=_parallel_value(descriptions, index),
                technologies=_parse_csv(_parallel_value(technologies, index)),
                outcomes=_parse_csv(_parallel_value(outcomes, index)),
            )
        )
    return projects


def _parse_education_lines(value: str) -> list[ResumeEducation]:
    education = []
    for line in _split_lines(value):
        parts = [part.strip() for part in line.split("|")]
        education.append(
            ResumeEducation(
                school=parts[0] if len(parts) > 0 else "",
                degree=parts[1] if len(parts) > 1 else "",
                major=parts[2] if len(parts) > 2 else "",
                startDate=parts[3] if len(parts) > 3 else "",
                endDate=parts[4] if len(parts) > 4 else "",
            )
        )
    return education


def _parse_education_items(
    schools: list[str],
    degrees: list[str],
    majors: list[str],
    periods: list[str],
) -> list[ResumeEducation]:
    education = []
    for index, school in enumerate(schools):
        if not school.strip():
            continue
        start_date, end_date = _parse_period(_parallel_value(periods, index))
        education.append(
            ResumeEducation(
                school=school.strip(),
                degree=_parallel_value(degrees, index),
                major=_parallel_value(majors, index),
                startDate=start_date,
                endDate=end_date,
            )
        )
    return education


def _parse_certificate_lines(value: str) -> list[ResumeCertificate]:
    certificates = []
    for line in _split_lines(value):
        parts = [part.strip() for part in line.split("|")]
        certificates.append(
            ResumeCertificate(
                name=parts[0] if len(parts) > 0 else "",
                issuer=parts[1] if len(parts) > 1 else "",
                date=parts[2] if len(parts) > 2 else "",
            )
        )
    return certificates


def _parse_certificate_items(
    names: list[str],
    issuers: list[str],
    dates: list[str],
) -> list[ResumeCertificate]:
    certificates = []
    for index, name in enumerate(names):
        if not name.strip():
            continue
        certificates.append(
            ResumeCertificate(
                name=name.strip(),
                issuer=_parallel_value(issuers, index),
                date=_parallel_value(dates, index),
            )
        )
    return certificates


def _parse_language_lines(value: str) -> list[ResumeLanguage]:
    languages = []
    for line in _split_lines(value):
        parts = [part.strip() for part in line.replace("//", "|").split("|", 1)]
        languages.append(
            ResumeLanguage(
                name=parts[0] if len(parts) > 0 else "",
                proficiency=parts[1] if len(parts) > 1 else "",
            )
        )
    return languages


def _parse_language_items(
    names: list[str],
    proficiencies: list[str],
) -> list[ResumeLanguage]:
    languages = []
    for index, name in enumerate(names):
        if not name.strip():
            continue
        languages.append(
            ResumeLanguage(
                name=name.strip(),
                proficiency=_parallel_value(proficiencies, index),
            )
        )
    return languages


def _resume_edit_context(resume) -> dict[str, str]:
    return {
        "skills": "\n".join(resume.skills),
        "links": "\n".join(resume.contact.links),
        "experiences": _format_experiences(resume.experiences),
        "education": _format_education(resume.education),
        "certificates": _format_certificates(resume.certificates),
        "projects": _format_projects(resume.projects),
        "languages": _format_languages(resume.languages),
    }


def _format_experiences(experiences: list[ResumeExperience]) -> str:
    blocks = []
    for item in experiences:
        period = " - ".join(value for value in [item.start_date, item.end_date] if value)
        blocks.append(
            "\n".join(
                [
                    f"title: {item.title}",
                    f"company: {item.company}",
                    f"period: {period}",
                    f"summary: {item.summary}",
                    f"achievements: {', '.join(item.achievements)}",
                    f"technologies: {', '.join(item.technologies)}",
                ]
            )
        )
    return "\n---\n".join(blocks)


def _format_projects(projects: list[ResumeProject]) -> str:
    blocks = []
    for item in projects:
        blocks.append(
            "\n".join(
                [
                    f"name: {item.name}",
                    f"role: {item.role}",
                    f"description: {item.description}",
                    f"technologies: {', '.join(item.technologies)}",
                    f"outcomes: {', '.join(item.outcomes)}",
                ]
            )
        )
    return "\n---\n".join(blocks)


def _format_education(education: list[ResumeEducation]) -> str:
    return "\n".join(
        " | ".join(
            [
                item.school,
                item.degree,
                item.major,
                item.start_date,
                item.end_date,
            ]
        )
        for item in education
    )


def _format_certificates(certificates: list[ResumeCertificate]) -> str:
    return "\n".join(
        " | ".join([item.name, item.issuer, item.date]) for item in certificates
    )


def _format_languages(languages: list[ResumeLanguage]) -> str:
    return "\n".join(
        " | ".join([item.name, item.proficiency]) for item in languages
    )

from __future__ import annotations

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.schemas.role import RoleProfile
from app.services.role_service import RoleService
from app.services.resume_normalization_service import ResumeNormalizationService
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
def role_detail(request: Request, role_id: str) -> HTMLResponse:
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
            "normalization_result": None,
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
    profile = role_service.load_profile(role_id)
    resume = ResumeRepository(role_path).load()

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
            "normalization_result": result,
        },
    )


def _has_profile_content(profile: RoleProfile) -> bool:
    return any(
        [
            profile.name.strip(),
            profile.skills.strip(),
            profile.career.strip(),
            profile.autobiography.strip(),
        ]
    )

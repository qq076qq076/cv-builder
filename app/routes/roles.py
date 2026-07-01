from __future__ import annotations

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.schemas.role import RoleProfile
from app.services.role_service import RoleService
from app.storage.evidence import EvidenceRepository

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
    return templates.TemplateResponse(
        request,
        "role_detail.html",
        context={
            "request": request,
            "role": role,
            "profile": role_service.load_profile(role_id),
            "sources": EvidenceRepository(role_path).list_sources().sources,
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


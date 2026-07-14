from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.services.import_service import ImportService, UploadValidationError, read_limited_upload
from app.services.role_service import RoleService
from app.services.resume_normalization_service import ResumeNormalizationService

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/import", response_class=HTMLResponse)
def legacy_import_page() -> RedirectResponse:
    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/roles/{role_id}/import/files", response_class=HTMLResponse)
async def upload_file(
    request: Request,
    role_id: str,
    resume_file: UploadFile = File(...),
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

    service = ImportService(role_service.role_path(role_id))
    try:
        saved_upload = service.save_uploaded_file(
            filename=resume_file.filename or "upload",
            content_type=resume_file.content_type,
            content=await read_limited_upload(resume_file),
        )
    except UploadValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    _normalize_imported_source(
        settings=settings,
        role_service=role_service,
        role_id=role_id,
        source_id=saved_upload.source.id,
        should_normalize=not saved_upload.is_duplicate,
    )

    return RedirectResponse(f"/roles/{role_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/roles/{role_id}/import/sources/{source_id}/reprocess", response_class=HTMLResponse)
def reprocess_source(request: Request, role_id: str, source_id: str) -> HTMLResponse:
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

    service = ImportService(role_service.role_path(role_id))
    saved_upload = service.reprocess_source(source_id)
    _normalize_imported_source(
        settings=settings,
        role_service=role_service,
        role_id=role_id,
        source_id=saved_upload.source.id if saved_upload else source_id,
        should_normalize=saved_upload is not None,
    )

    return RedirectResponse(f"/roles/{role_id}", status_code=status.HTTP_303_SEE_OTHER)


def _normalize_imported_source(
    *,
    settings,
    role_service: RoleService,
    role_id: str,
    source_id: str,
    should_normalize: bool,
) -> None:
    if not should_normalize:
        return

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

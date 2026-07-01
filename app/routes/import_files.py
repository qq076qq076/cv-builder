from __future__ import annotations

from fastapi import APIRouter, File, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.schemas.workspace import WorkspaceStatus
from app.services.dashboard_service import DashboardService
from app.services.import_service import ImportService
from app.services.role_service import RoleService
from app.services.resume_normalization_service import (
    ResumeNormalizationResult,
    ResumeNormalizationService,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/import", response_class=HTMLResponse)
def legacy_import_page() -> RedirectResponse:
    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/roles/{role_id}/import", response_class=HTMLResponse)
def import_page(request: Request, role_id: str) -> HTMLResponse:
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

    return _render_import_page(
        request,
        service=service,
        role=role,
    )


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
    saved_upload = service.save_uploaded_file(
        filename=resume_file.filename or "upload",
        content_type=resume_file.content_type,
        content=await resume_file.read(),
    )
    normalization_result = _normalize_imported_source(
        settings=settings,
        role_service=role_service,
        role_id=role_id,
        source_id=saved_upload.source.id,
        should_normalize=(
            not saved_upload.is_duplicate
            and saved_upload.source.extraction_status == "completed"
            and saved_upload.source.extracted_text_path is not None
        ),
    )

    return _render_import_page(
        request,
        service=service,
        role=role,
        uploaded_filename=resume_file.filename,
        saved_source=saved_upload.source,
        text_preview=_preview_text(saved_upload.extracted_text),
        is_duplicate=saved_upload.is_duplicate,
        normalization_result=normalization_result,
    )


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
    normalization_result = _normalize_imported_source(
        settings=settings,
        role_service=role_service,
        role_id=role_id,
        source_id=saved_upload.source.id if saved_upload else source_id,
        should_normalize=(
            saved_upload is not None
            and saved_upload.source.extraction_status == "completed"
            and saved_upload.source.extracted_text_path is not None
        ),
    )

    return _render_import_page(
        request,
        service=service,
        role=role,
        reprocessed_source=saved_upload.source if saved_upload else None,
        text_preview=_preview_text(saved_upload.extracted_text) if saved_upload else None,
        reprocess_missing=saved_upload is None,
        normalization_result=normalization_result,
    )


def _render_import_page(
    request: Request,
    *,
    service: ImportService,
    role,
    uploaded_filename: str | None = None,
    saved_source=None,
    text_preview: str | None = None,
    is_duplicate: bool = False,
    reprocessed_source=None,
    reprocess_missing: bool = False,
    normalization_result: ResumeNormalizationResult | None = None,
) -> HTMLResponse:
    state = DashboardService(service.workspace_path).get_state()

    return templates.TemplateResponse(
        request,
        "import.html",
        context={
            "request": request,
            "state": state,
            "status": state.status,
            "workspace_status": WorkspaceStatus,
            "role": role,
            "sources": service.evidence_repository.list_sources().sources,
            "uploaded_filename": uploaded_filename,
            "saved_source": saved_source,
            "text_preview": text_preview,
            "is_duplicate": is_duplicate,
            "reprocessed_source": reprocessed_source,
            "reprocess_missing": reprocess_missing,
            "normalization_result": normalization_result,
        },
    )


def _preview_text(text: str | None, limit: int = 1200) -> str | None:
    if text is None:
        return None

    normalized = text.strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit]}..."


def _normalize_imported_source(
    *,
    settings,
    role_service: RoleService,
    role_id: str,
    source_id: str,
    should_normalize: bool,
) -> ResumeNormalizationResult | None:
    if not should_normalize:
        return None

    role_path = role_service.role_path(role_id)
    result = ResumeNormalizationService(
        role_path=role_path,
        api_key=settings.openai_api_key,
        model=settings.openai_model,
    ).normalize_source(source_id)
    if result.status == "completed" and result.resume is not None:
        role_service.sync_profile_from_resume(role_id, result.resume)
    return result

from __future__ import annotations

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.schemas.workspace import WorkspaceStatus
from app.services.dashboard_service import DashboardService
from app.services.import_service import ImportService

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/import", response_class=HTMLResponse)
def import_page(request: Request) -> HTMLResponse:
    settings = get_settings()
    service = ImportService(settings.workspace_path)

    return _render_import_page(
        request,
        service=service,
    )


@router.post("/import/files", response_class=HTMLResponse)
async def upload_file(request: Request, resume_file: UploadFile = File(...)) -> HTMLResponse:
    settings = get_settings()
    service = ImportService(settings.workspace_path)
    saved_upload = service.save_uploaded_file(
        filename=resume_file.filename or "upload",
        content_type=resume_file.content_type,
        content=await resume_file.read(),
    )

    return _render_import_page(
        request,
        service=service,
        uploaded_filename=resume_file.filename,
        saved_source=saved_upload.source,
        text_preview=_preview_text(saved_upload.extracted_text),
        is_duplicate=saved_upload.is_duplicate,
    )


@router.post("/import/sources/{source_id}/reprocess", response_class=HTMLResponse)
def reprocess_source(request: Request, source_id: str) -> HTMLResponse:
    settings = get_settings()
    service = ImportService(settings.workspace_path)
    saved_upload = service.reprocess_source(source_id)

    return _render_import_page(
        request,
        service=service,
        reprocessed_source=saved_upload.source if saved_upload else None,
        text_preview=_preview_text(saved_upload.extracted_text) if saved_upload else None,
        reprocess_missing=saved_upload is None,
    )


def _render_import_page(
    request: Request,
    *,
    service: ImportService,
    uploaded_filename: str | None = None,
    saved_source=None,
    text_preview: str | None = None,
    is_duplicate: bool = False,
    reprocessed_source=None,
    reprocess_missing: bool = False,
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
            "sources": service.evidence_repository.list_sources().sources,
            "uploaded_filename": uploaded_filename,
            "saved_source": saved_source,
            "text_preview": text_preview,
            "is_duplicate": is_duplicate,
            "reprocessed_source": reprocessed_source,
            "reprocess_missing": reprocess_missing,
        },
    )


def _preview_text(text: str | None, limit: int = 1200) -> str | None:
    if text is None:
        return None

    normalized = text.strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit]}..."

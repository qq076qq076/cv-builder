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
    state = DashboardService(settings.workspace_path).get_state()

    return templates.TemplateResponse(
        request,
        "import.html",
        context={
            "request": request,
            "state": state,
            "status": state.status,
            "workspace_status": WorkspaceStatus,
            "uploaded_filename": None,
            "saved_source": None,
        },
    )


@router.post("/import/files", response_class=HTMLResponse)
async def upload_file(request: Request, resume_file: UploadFile = File(...)) -> HTMLResponse:
    settings = get_settings()
    saved_upload = ImportService(settings.workspace_path).save_uploaded_file(
        filename=resume_file.filename or "upload",
        content_type=resume_file.content_type,
        content=await resume_file.read(),
    )
    state = DashboardService(settings.workspace_path).get_state()

    return templates.TemplateResponse(
        request,
        "import.html",
        context={
            "request": request,
            "state": state,
            "status": state.status,
            "workspace_status": WorkspaceStatus,
            "uploaded_filename": resume_file.filename,
            "saved_source": saved_upload.source,
        },
    )

from __future__ import annotations

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.schemas.workspace import WorkspaceStatus
from app.services.dashboard_service import DashboardService
from app.storage.workspace import ensure_workspace_dirs

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/workspace", response_class=HTMLResponse)
def workspace(request: Request) -> HTMLResponse:
    settings = get_settings()
    state = DashboardService(settings.workspace_path).get_state()

    return templates.TemplateResponse(
        request,
        "workspace.html",
        context={
            "request": request,
            "state": state,
            "status": state.status,
            "workspace_status": WorkspaceStatus,
        },
    )


@router.post("/workspace/create")
def create_workspace() -> RedirectResponse:
    settings = get_settings()
    ensure_workspace_dirs(settings.workspace_path)

    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)


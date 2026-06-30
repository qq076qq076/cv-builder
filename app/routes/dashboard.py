from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.schemas.workspace import WorkspaceStatus
from app.services.dashboard_service import DashboardService

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    settings = get_settings()
    state = DashboardService(settings.workspace_path).get_state()

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        context={
            "request": request,
            "state": state,
            "status": state.status,
            "workspace_status": WorkspaceStatus,
        },
    )

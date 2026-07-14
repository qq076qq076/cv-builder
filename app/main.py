from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routes.dashboard import router as dashboard_router
from app.routes.import_files import router as import_files_router
from app.routes.roles import router as roles_router
from app.routes.workspace import router as workspace_router
from app.config import get_settings
from app.services.role_service import RoleService
from app.storage.generation_tasks import GenerationTaskRepository

def create_app() -> FastAPI:
    app = FastAPI(title="AI Career Copilot")

    settings = get_settings()
    role_service = RoleService(settings.workspace_path)
    for role in role_service.list_roles():
        GenerationTaskRepository(role_service.role_path(role.id)).recover_interrupted_tasks()

    app.mount("/static", StaticFiles(directory="app/static"), name="static")
    app.include_router(dashboard_router)
    app.include_router(roles_router)
    app.include_router(import_files_router)
    app.include_router(workspace_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()

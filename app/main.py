from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routes.dashboard import router as dashboard_router

def create_app() -> FastAPI:
    app = FastAPI(title="AI Career Copilot")

    app.mount("/static", StaticFiles(directory="app/static"), name="static")
    app.include_router(dashboard_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()

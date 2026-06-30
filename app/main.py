from fastapi import FastAPI
from fastapi.responses import HTMLResponse


def create_app() -> FastAPI:
    app = FastAPI(title="AI Career Copilot")

    @app.get("/health", response_class=HTMLResponse)
    def health() -> str:
        return "ok"

    return app


app = create_app()


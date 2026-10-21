"""Compose the backend API and optionally serve the built dashboard."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.api.dependencies import Services
from backend.api.errors import register_error_handlers
from backend.api.routes import assistant, expenses, reports, sessions, workspace
from backend.assistant.service import ReportAssistant
from backend.config import PROJECT_ROOT


def create_app(project_root: Path | None = None) -> FastAPI:
    """Create an independent application for the project or a fixture directory."""
    root = Path(project_root) if project_root is not None else PROJECT_ROOT
    application = FastAPI(title="Expense Policy Checker", version="1.0.0")
    application.state.services = Services.create(root)
    application.state.assistant = ReportAssistant(root)
    register_error_handlers(application)
    for routes in (sessions, reports, expenses, workspace, assistant):
        application.include_router(routes.router)

    # Vite proxies /api in development; production can use this single server.
    dist = root / "frontend" / "dist"
    if dist.is_dir():
        application.mount("/", StaticFiles(directory=dist, html=True), name="dashboard")
    return application


app = create_app()

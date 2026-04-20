"""FastAPI application — Ariya Email Assistant."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.routes import router as api_router
from app.config import settings
from app.database import init_db
from app.services.scheduler_service import start_scheduler, stop_scheduler

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Ariya Email Assistant...")
    init_db()
    start_scheduler()
    yield
    stop_scheduler()
    logger.info("Ariya Email Assistant stopped.")


app = FastAPI(
    title=settings.app_title,
    version="1.0.0",
    lifespan=lifespan,
)

# Mount static files
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")

# Include API routes
app.include_router(api_router)


# ── Dashboard pages ───────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(request, "dashboard.html")


@app.get("/emails", response_class=HTMLResponse)
async def emails_page(request: Request):
    return templates.TemplateResponse(request, "emails.html")


@app.get("/tasks", response_class=HTMLResponse)
async def tasks_page(request: Request):
    return templates.TemplateResponse(request, "tasks.html")


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    return templates.TemplateResponse(request, "settings.html")


@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.app_title}

"""FastAPI application — Ariya Email Assistant."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.routes import router as api_router
from app.config import settings
from app.database import init_db
from app.services.scheduler_service import start_scheduler, stop_scheduler
from app.services.settings_store import apply_saved_on_startup

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
    apply_saved_on_startup()
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


@app.get("/sales", response_class=HTMLResponse)
async def sales_page(request: Request):
    return templates.TemplateResponse(request, "sales.html")


@app.get("/customers", response_class=HTMLResponse)
async def customers_page(request: Request):
    return templates.TemplateResponse(request, "customers.html")


@app.get("/prices", response_class=HTMLResponse)
async def prices_page(request: Request):
    return templates.TemplateResponse(request, "prices.html")


@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.app_title}


# ── Microsoft OAuth2 ──────────────────────────────────────────────────────────

@app.get("/auth/login")
async def auth_login():
    """Redirect user to Microsoft login page."""
    from app.services.oauth_service import get_auth_url, is_configured
    if not is_configured():
        return HTMLResponse(
            "<h2>OAuth2 not configured</h2>"
            "<p>Set MS_CLIENT_ID and MS_CLIENT_SECRET in settings.</p>"
        )
    url = get_auth_url()
    if not url:
        return HTMLResponse("<h2>Failed to generate login URL</h2>")
    return RedirectResponse(url)


@app.get("/auth/callback")
async def auth_callback(request: Request):
    """Handle Microsoft OAuth2 callback."""
    from app.services.oauth_service import handle_callback
    result = handle_callback(dict(request.query_params))
    if "error" in result:
        return templates.TemplateResponse(request, "auth_result.html", {
            "success": False,
            "error": result["error"],
        })
    return templates.TemplateResponse(request, "auth_result.html", {
        "success": True,
        "email": result.get("email", ""),
        "name": result.get("name", ""),
    })


@app.get("/auth/status")
async def auth_status():
    """Check if user is signed in with Microsoft."""
    from app.services.oauth_service import get_signed_in_user, is_configured
    if not is_configured():
        return {"configured": False, "signed_in": False}
    user = get_signed_in_user()
    if user:
        return {"configured": True, "signed_in": True, **user}
    return {"configured": True, "signed_in": False}


@app.post("/auth/signout")
async def auth_signout():
    """Sign out of Microsoft account."""
    from app.services.oauth_service import sign_out
    sign_out()
    return {"ok": True}

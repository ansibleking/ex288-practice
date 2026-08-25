from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app.audit import AuditStore
from app.config import Settings, get_settings
from app.jira_client import JiraClient, JiraClientError
from app.routers import approvals, audit, feed, pending, schedule, sheets, tickets
from app.routers import settings as settings_router
from app.runtime_settings import effective_provider
from app.schedule_store import ScheduleStore
from app.scheduler_runner import scheduler_loop

logger = logging.getLogger(__name__)

FRONTEND_DIST = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.jira_client = JiraClient(settings)
    app.state.audit_store = AuditStore(settings.database_path)
    app.state.schedule_store = ScheduleStore(settings.database_path)
    scheduler_task = asyncio.create_task(
        scheduler_loop(
            app.state.schedule_store,
            app.state.jira_client,
            settings,
            app.state.audit_store,
            settings.scheduler_poll_seconds,
        )
    )
    try:
        yield
    finally:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass
        await app.state.jira_client.aclose()


app = FastAPI(title="TriageDesk", lifespan=lifespan)
app.include_router(feed.router)
app.include_router(pending.router)
app.include_router(audit.router)
app.include_router(tickets.router)
app.include_router(schedule.router)
app.include_router(approvals.router)
app.include_router(sheets.router)
app.include_router(settings_router.router)


@app.get("/api/health")
async def health(settings: Settings = Depends(get_settings)) -> dict:
    current_provider = effective_provider(settings)
    llm_configured = (
        bool(settings.onprem_llm_base_url)
        if current_provider == "onprem"
        else bool(settings.anthropic_api_key)
    )
    result: dict = {
        "llm_provider": current_provider,
        "llm_model": settings.default_llm_model,
        "llm_configured": llm_configured,
        "reporting_service_configured": settings.reporting_service_configured,
    }
    try:
        me = await app.state.jira_client.whoami()
        result["jira_reachable"] = True
        result["jira_user"] = me.get("displayName")
    except JiraClientError as exc:
        result["jira_reachable"] = False
        result["jira_error"] = str(exc)
    return result


# The React build is copied into app/static during the Docker image build.
# In local dev without a build present, only the API is served.
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")


@app.middleware("http")
async def no_cache_index(request: Request, call_next):
    """Vite's hashed asset filenames (/assets/*.js, *.css) are safe to cache
    forever -- their content only changes when their filename does. index.html
    references those hashes by name, so if *it* gets cached (by the browser or
    a proxy in between), a rebuild ships new assets but the browser keeps
    requesting the old bundle by its old, stale reference. Force revalidation
    on everything that isn't a hashed asset so a redeploy is always visible.
    """
    response = await call_next(request)
    if "/assets/" not in request.url.path:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response

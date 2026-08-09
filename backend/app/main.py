"""FastAPI application entry point."""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# StrEnum and PEP 604 unions in class bodies need 3.11. Failing here with a
# sentence beats failing three imports deep with an ImportError.
if sys.version_info < (3, 11):  # pragma: no cover - version-dependent
    raise SystemExit(
        f"CohortIQ needs Python 3.11 or newer (found {sys.version.split()[0]}). "
        "Install 3.11+, then: pip install -r backend/requirements.txt"
    )

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import interview, meta
from .api.deps import build_services, get_services, shutdown_services
from .config import PROJECT_ROOT, get_settings

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
log = logging.getLogger("cohortiq")


@asynccontextmanager
async def lifespan(app: FastAPI):
    services = build_services(settings)
    removed = services.store.sweep()
    log.info(
        "CohortIQ up | provider chain=%s | expired sessions swept=%d",
        services.router.health()["chain"],
        removed,
    )
    if not services.router.is_live():
        # Not a warning: this is a supported mode, not a misconfiguration.
        log.info(
            "Running on the offline rubric engine — no API key needed. The full interview works: "
            "planning, adaptive questioning, scoring and reporting. Questions are composed from "
            "curriculum objectives rather than model-written. Set ANTHROPIC_API_KEY, OPENAI_API_KEY "
            "or GROQ_API_KEY if you want model-written questions."
        )
    yield
    await shutdown_services()


app = FastAPI(
    title="CohortIQ — AI Interview Intelligence",
    version="1.0.0",
    description="Adaptive technical interviews grounded in a candidate's cohort learning record.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins) or ["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(interview.router, prefix="/api", tags=["interview"])
app.include_router(meta.router, prefix="/api", tags=["meta"])


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Keep the spec's response shape even when the request is malformed."""
    if request.url.path.endswith("/api/interview"):
        return JSONResponse(
            status_code=200,
            content={
                "reply": (
                    "I couldn't read that request — it needs a `sessionId`, plus a `candidate` "
                    "object on the first call or a `message` string after that."
                ),
                "done": False,
            },
        )
    return JSONResponse(status_code=422, content={"detail": exc.errors()[:5]})


@app.get("/api")
async def api_index() -> dict:
    return {
        "name": "CohortIQ",
        "endpoint": "POST /api/interview",
        "docs": "/docs",
        "health": "/api/health",
    }


# --------------------------------------------------------------------------
# Static frontend (served only when it has been built)
# --------------------------------------------------------------------------
_DIST = PROJECT_ROOT / "frontend" / "dist"
if _DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        target = _DIST / full_path
        if full_path and target.is_file():
            return FileResponse(target)
        return FileResponse(_DIST / "index.html")

else:

    @app.get("/", include_in_schema=False)
    async def root_placeholder() -> dict:
        return {
            "name": "CohortIQ",
            "ui": "not built — run `npm run build` in frontend/, or use the Vite dev server",
            "api": "/api",
        }

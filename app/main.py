"""
app/main.py
-----------
ClaimGuard RCM Engine — FastAPI application entry point.

Startup sequence
----------------
1. Instantiate FastAPI with project metadata sourced from ``Settings``.
2. Register CORS middleware (all origins allowed for demo; restrict in production).
3. Mount the v1 API router under the ``/api/v1`` prefix.
4. Expose a liveness probe at ``GET /health``.
5. Serve the interactive HTML dashboard at ``GET /`` from ``app/templates/index.html``.

Run locally
-----------
    uvicorn app.main:app --reload --port 8000

Interactive docs available at:
    http://localhost:8000/        (Live HTML Dashboard)
    http://localhost:8000/docs   (Swagger UI)
    http://localhost:8000/redoc  (ReDoc)
"""

from __future__ import annotations

from datetime import datetime, timezone

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from app.api.v1.router import api_v1_router
from app.core.config import settings

# ── Application Instance ──────────────────────────────────────────────────────

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description=settings.DESCRIPTION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    contact={
        "name": "ClaimGuard RCM Engineering",
        "email": "rcm-support@claimguard.internal",
    },
    license_info={
        "name": "Internal Use Only",
    },
)

# ── CORS Middleware ───────────────────────────────────────────────────────────
# Allows all origins in development/demo mode.
# In production: restrict ``allow_origins`` to your frontend domain(s).

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOW_ORIGINS,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=settings.CORS_ALLOW_METHODS,
    allow_headers=settings.CORS_ALLOW_HEADERS,
)

# ── API Router ────────────────────────────────────────────────────────────────
# Mount all v1 endpoints at /api/v1

app.include_router(api_v1_router, prefix=settings.API_V1_STR)


# ── Health Check ──────────────────────────────────────────────────────────────

@app.get(
    "/health",
    tags=["System"],
    summary="Liveness probe",
    description=(
        "Returns HTTP 200 with a JSON payload indicating the service is alive. "
        "Suitable for Kubernetes liveness/readiness probes and load-balancer health checks."
    ),
)
def health_check() -> JSONResponse:
    """
    Liveness probe endpoint.

    Returns
    -------
    JSONResponse
        JSON body with status, service name, version, and current UTC timestamp.
    """
    return JSONResponse(
        status_code=200,
        content={
            "status": "healthy",
            "service": settings.PROJECT_NAME,
            "version": settings.VERSION,
            "environment": settings.ENVIRONMENT,
            "timestamp_utc": datetime.now(tz=timezone.utc).isoformat(),
        },
    )


# ── HTML Dashboard ───────────────────────────────────────────────────────────

# Resolve the template path relative to this file so the route works regardless
# of the working directory from which uvicorn is launched.
_TEMPLATES_DIR = Path(__file__).parent / "templates"
_INDEX_HTML = _TEMPLATES_DIR / "index.html"


@app.get(
    "/",
    response_class=HTMLResponse,
    tags=["System"],
    summary="Interactive RCM Dashboard",
    description=(
        "Serves the ClaimGuard RCM interactive HTML dashboard. "
        "Loads KPI metrics automatically and provides controls for "
        "batch claim scrubbing and single-claim testing."
    ),
    include_in_schema=False,
)
def dashboard() -> HTMLResponse:
    """
    Serve the interactive HTML dashboard.

    The dashboard is a single-page HTML file located at
    ``app/templates/index.html``. It fetches data from the ``/api/v1``
    endpoints via vanilla JavaScript fetch calls.

    Returns
    -------
    HTMLResponse
        The full HTML page content with ``200 OK``.

    Raises
    ------
    HTTPException (500)
        If the template file is missing from the expected path.
    """
    if not _INDEX_HTML.exists():
        raise HTTPException(
            status_code=500,
            detail=(
                f"Dashboard template not found at '{_INDEX_HTML}'. "
                "Ensure 'app/templates/index.html' exists in the project tree."
            ),
        )
    return HTMLResponse(content=_INDEX_HTML.read_text(encoding="utf-8"), status_code=200)

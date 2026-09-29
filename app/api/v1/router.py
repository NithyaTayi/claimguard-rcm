"""
app/api/v1/router.py
---------------------
Top-level APIRouter for API version 1 of ClaimGuard RCM.

All domain routers are registered here with their respective path prefixes
and OpenAPI tags. The assembled ``api_v1_router`` is then mounted onto the
FastAPI application in ``app/main.py``.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import analytics, claims

# ── Version-1 root router ─────────────────────────────────────────────────────
api_v1_router = APIRouter()

# ── Claims domain ─────────────────────────────────────────────────────────────
api_v1_router.include_router(
    claims.router,
    prefix="/claims",
    tags=["Claims"],
)

# ── Analytics domain ──────────────────────────────────────────────────────────
api_v1_router.include_router(
    analytics.router,
    prefix="/analytics",
    tags=["Analytics"],
)

"""
app/core/config.py
------------------
Application-level settings using Pydantic BaseSettings.
All values can be overridden via environment variables or a .env file.
"""

from __future__ import annotations

from typing import List

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Project Identity ────────────────────────────────────────────────────
    PROJECT_NAME: str = "ClaimGuard RCM Engine"
    VERSION: str = "1.0.0"
    DESCRIPTION: str = (
        "A production-grade Revenue Cycle Management claim scrubber "
        "and denial-risk predictor powered by FastAPI."
    )

    # ── API Versioning ───────────────────────────────────────────────────────
    API_V1_STR: str = "/api/v1"

    # ── CORS Configuration ───────────────────────────────────────────────────
    # For development/demo, all origins are allowed.
    # In production, restrict this to specific domains.
    CORS_ALLOW_ORIGINS: List[str] = ["*"]
    CORS_ALLOW_CREDENTIALS: bool = True
    CORS_ALLOW_METHODS: List[str] = ["*"]
    CORS_ALLOW_HEADERS: List[str] = ["*"]

    # ── Debug / Environment ──────────────────────────────────────────────────
    DEBUG: bool = False
    ENVIRONMENT: str = "development"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
    }


# Singleton settings instance consumed throughout the application
settings = Settings()

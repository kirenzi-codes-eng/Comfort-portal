from __future__ import annotations

import os
from pathlib import Path

# FastAPI serves the app logo while Streamlit remains responsible only for the UI.
FASTAPI_BASE = os.getenv("FASTAPI_BASE", "http://127.0.0.1:8000").rstrip("/")


def _get_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def get_logo_url() -> str:
    """Return the public URL for the portal logo served by FastAPI."""
    return f"{FASTAPI_BASE}/logo.png"

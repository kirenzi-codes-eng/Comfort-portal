from pathlib import Path

from src.utils import pwa


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app.py"
FASTAPI_BASE = "http://127.0.0.1:8000"


def test_logo_url_helper_still_works():
    assert pwa.get_logo_url() == f"{FASTAPI_BASE}/logo.png"


def test_app_no_longer_registers_service_workers_or_firebase():
    app_content = APP_PATH.read_text(encoding="utf-8")
    lowered = app_content.lower()
    assert "serviceworker" not in lowered
    assert "firebase" not in lowered
    assert "navigator.serviceworker.register" not in lowered
    assert "manifest" not in lowered

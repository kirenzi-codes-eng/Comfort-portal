from __future__ import annotations
import base64
import importlib.util
import logging
import os
from pathlib import Path
from typing import Any
import streamlit as st
from PIL import Image
import io

ROOT = Path(__file__).resolve().parent
STYLE_CSS_PATH = ROOT / "style.css"

APP_NAME = "Comfort Group Portal"
APP_SHORT_NAME = "Comfort Portal"
APP_THEME_COLOR = "#2563eb"

SRC = ROOT / "src"


def load_css() -> None:
    if not STYLE_CSS_PATH.exists():
        return

    if st.session_state.get("global_css_loaded", False):
        return

    with STYLE_CSS_PATH.open("r", encoding="utf-8") as handle:
        st.markdown(f"<style>{handle.read()}</style>", unsafe_allow_html=True)

    st.session_state["global_css_loaded"] = True

# Set global page config early to override Streamlit branding.
# Load local logo.png safely with PIL and use it as the page icon.
try:
    logo_path = ROOT / "logo.png"
    if logo_path.exists():
        _logo_img = Image.open(logo_path)
        try:
            # Convert and resize to recommended favicon size to avoid large icons
            resample_filter = getattr(getattr(Image, "Resampling", None), "LANCZOS", None) or getattr(Image, "LANCZOS", None)
            _logo_img = _logo_img.convert("RGBA")
            _logo_img = _logo_img.resize((32, 32), resample_filter)
        except Exception:
            # If conversion/resizing fails, fall back to the original image
            pass
    else:
        _logo_img = None
except Exception:
    _logo_img = None

try:
    # Convert image to PNG bytes for predictable Streamlit behavior
    _logo_icon = None
    _logo_data_uri = None
    try:
        if _logo_img is not None:
            buf = io.BytesIO()
            _logo_img.save(buf, format="PNG")
            buf.seek(0)
            _logo_icon = buf.getvalue()
            _logo_data_uri = f"data:image/png;base64,{base64.b64encode(_logo_icon).decode('ascii')}"
    except Exception:
        _logo_icon = None
        _logo_data_uri = None

    st.set_page_config(page_title=APP_NAME, page_icon=_logo_icon or "📘", layout="wide")
    st.markdown(
        """
        <style>
            [data-testid="stDecoration"],
            footer {
                visibility: hidden !important;
                display: none !important;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )

    if _logo_data_uri is not None:
        st.markdown(
            f"""
            <link rel="apple-touch-icon" sizes="180x180" href="{_logo_data_uri}">
            <meta name="apple-mobile-web-app-title" content="{APP_NAME}">
            <meta name="application-name" content="{APP_NAME}">
            <meta name="theme-color" content="{APP_THEME_COLOR}">
            <meta name="msapplication-TileColor" content="{APP_THEME_COLOR}">
            <link rel="icon" type="image/png" sizes="32x32" href="{_logo_data_uri}">
            """,
            unsafe_allow_html=True,
        )
except Exception:
    # If Streamlit has already been configured elsewhere, ignore to avoid crash.
    pass

MODULE_CONFIG = {
    "Core Services": [
        {
            "title": "Home",
            "path": SRC / "views" / "home.py",
            "candidates": ["home_view"],
            "icon": "🏠",
        },
        {
            "title": "Subscriptions",
            "path": SRC / "views" / "subscriptions.py",
            "candidates": ["subscriptions_view"],
            "icon": "💳",
        },
        {
            "title": "Savings",
            "path": SRC / "views" / "savings.py",
            "candidates": ["savings_view"],
            "icon": "🏦",
        },
        {
            "title": "Loans Management",
            "path": SRC / "views" / "loans.py",
            "candidates": ["loans_view"],
            "icon": "💼",
        },
        {
            "title": "Sharing",
            "path": SRC / "views" / "sharing.py",
            "candidates": ["sharing_view"],
            "icon": "📈",
        },
        {
            "title": "Group Chat",
            "path": SRC / "components" / "chat.py",
            "candidates": ["chat_view"],
            "icon": "💬",
        },
        {
            "title": "Inquiry",
            "path": SRC / "views" / "inquiry.py",
            "candidates": ["inquiry_view"],
            "icon": "📩",
        },
        {
            "title": "Subscription Monitor",
            "path": SRC / "views" / "subscriptions.py",
            "candidates": ["chairperson_monitor_view"],
            "icon": "📊",
            "roles": ["Chairperson"],
        },
        {
            "title": "Admin Docs",
            "path": SRC / "views" / "admin_docs.py",
            "candidates": ["admin_docs_view"],
            "icon": "🗂️",
            "roles": ["Chairperson", "Secretary", "Treasurer", "Vice Chairperson", "Welfare"],
        },
    ],
    "Account & Security": [
        {
            "title": "Profile",
            "path": SRC / "views" / "profile.py",
            "candidates": ["profile_view"],
            "icon": "👤",
        },
        {
            "title": "Family Registry",
            "path": SRC / "views" / "family.py",
            "candidates": ["family_view"],
            "icon": "👥",
        },
    ],
}

AUTH_MODULE_PATH = SRC / "components" / "auth.py"
AUTH_CANDIDATES = ["auth_ui"]
LOGOUT_KEYS = ["logged_in", "user_id", "user_name", "user_role", "user_status"]

_MODULE_CACHE: dict[str, Any] = {}

def import_module_from_path(path: Path):
    path_str = str(path.resolve())
    if path_str in _MODULE_CACHE:
        return _MODULE_CACHE[path_str]

    spec = importlib.util.spec_from_file_location(path.stem, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _MODULE_CACHE[path_str] = module
    return module

def find_view_func(module: Any, candidates: list[str]) -> Any | None:
    for name in candidates:
        if hasattr(module, name):
            return getattr(module, name)
    return None

def clear_session_state() -> None:
    # 1. Clear your application's authentication states
    for key in LOGOUT_KEYS:
        if key in st.session_state:
            del st.session_state[key]

    st.session_state["logged_in"] = False

    # 2. Clear Streamlit's internal navigation and query routing cache
    st.query_params.clear()

    # 3. Purge standard multi-page tracking keys if present
    for key in list(st.session_state.keys()):
        key_str = str(key).lower()
        if "page" in key_str or "nav" in key_str:
            del st.session_state[key]


def should_render_navigation(logged_in: bool | None) -> bool:
    return bool(logged_in)


def get_sidebar_initial_state(logged_in: bool | None) -> str:
    return "expanded" if should_render_navigation(logged_in) else "collapsed"


def apply_shell_layout(logged_in: bool | None) -> None:
    # Page config is set at module import time to ensure branding and icon are applied.
    # Avoid calling `st.set_page_config` here to prevent duplicate-initialization errors.

    if not should_render_navigation(logged_in):
        st.markdown(
            """
            <style>
            [data-testid="stSidebar"] {
                display: none !important;
                width: 0px !important;
                min-width: 0px !important;
            }
            section[data-testid="stSidebar"] {
                display: none !important;
            }
            .block-container {
                padding-top: 0.5rem !important;
                padding-left: 1rem !important;
                padding-right: 1rem !important;
            }
            header[data-testid="stHeader"] {
                display: none !important;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )


def build_menu(user_role: str | None = None) -> dict[str, list[dict[str, Any]]]:
    menu: dict[str, list[dict[str, Any]]] = {}
    for section, entries in MODULE_CONFIG.items():
        visible_entries = []
        for entry in entries:
            if not entry["path"].exists():
                continue
            allowed_roles = entry.get("roles")
            if allowed_roles and user_role not in allowed_roles:
                continue
            visible_entries.append(entry)
        if visible_entries:
            menu[section] = visible_entries
    return menu

def build_navigation_sections(user_role: str | None = None) -> list[Any]:
    page_list: list[Any] = []
    menu = build_menu(user_role)
    for entries in menu.values():
        for entry in entries:
            try:
                module = import_module_from_path(entry["path"])
                page_runner = find_view_func(module, entry["candidates"])
                if page_runner is None:
                    continue
                page_list.append(
                    st.Page(
                        page_runner,
                        title=entry["title"],
                        icon=entry["icon"],
                    )
                )
            except Exception as e:
                st.error(f"Error loading {entry['title']}: {e}")
    return page_list

def main() -> None:
    load_css()
    logged_in = bool(st.session_state.get("logged_in", False))
    apply_shell_layout(logged_in)

    # 2. Render view context dynamically based on state
    if not logged_in:
        # Dynamically pull authentication module details
        auth_module = import_module_from_path(AUTH_MODULE_PATH)
        auth_func = find_view_func(auth_module, AUTH_CANDIDATES)
        
        if auth_func is None:
            st.error("Authentication view function not found.")
            return

        # Render the login UI directly without passing it into st.navigation
        auth_func()
    else:
        # Build multi-page navigation view only for authenticated users
        user_role = st.session_state.get("user_role", "Member")
        navigation_pages = build_navigation_sections(user_role)
        
        if not navigation_pages:
            st.info("No pages are available right now.")
            return

        # Setup standard navigation frame
        if "selected_page" not in st.session_state:
            st.session_state.selected_page = "Home"

        selected_page = st.navigation(navigation_pages, position="sidebar", expanded=True)
        if selected_page is None:
            selected_page = next((page for page in navigation_pages if getattr(page, "title", None) == st.session_state.selected_page), None)

        # Build sidebar profile and asset elements 
        user_name = st.session_state.get("user_name", "Member")
        user_id = st.session_state.get("user_id", "ID unavailable")
        
        st.sidebar.markdown(
            f"""
            <div style="margin-bottom: 18px; padding: 16px 16px 14px; border-radius: 18px; background: #eff6ff; border: 1px solid #dbeafe;">
                <div style="font-size: 1rem; font-weight: 700; color: #1e3a8a;">{user_name}</div>
                <div style="font-size: 0.83rem; color: #a8a29e; margin-top: 4px; letter-spacing: 0.02em;">{user_id}</div>
                <div style="font-size: 0.83rem; color: #22c55e; margin-top: 4px; letter-spacing: 0.01em;">{user_role}</div>
            </div>
            """, 
            unsafe_allow_html=True,
        )
        
        logo_path = ROOT / "logo.png"
        if logo_path.exists():
            st.sidebar.markdown("---")
            st.sidebar.image(str(logo_path), width='stretch')

        # Logout processing block
        if st.sidebar.button("Logout"):
            clear_session_state()
            st.rerun()

        if selected_page is not None:
            st.session_state.selected_page = getattr(selected_page, "title", "Home")
            selected_page.run()

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.ERROR,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        main()
    except Exception as exc:
        logging.error("Unexpected application error:", exc_info=True)

        debug_mode = str(os.getenv("APP_DEBUG", "false")).strip().lower() == "true"
        if debug_mode:
            st.exception(exc)
        else:
            st.markdown(
                """
                <div style="max-width: 840px; margin: 28px auto; padding: 24px; border-radius: 22px; background: linear-gradient(135deg, #eef2ff 0%, #dbeafe 100%); border: 1px solid #bfdbfe; box-shadow: 0 18px 45px rgba(30, 64, 175, 0.08);">
                    <h2 style="margin: 0 0 12px; color: #1e3a8a; font-size: 1.55rem; font-weight: 700;">Connection delay detected</h2>
                    <p style="margin: 0 0 14px; color: #475569; font-size: 1rem; line-height: 1.7;">
                        We’re experiencing a temporary network or database delay. The portal is pausing while we reconnect gracefully.
                    </p>
                    <p style="margin: 0; color: #0f172a; font-size: 0.95rem; font-weight: 600; letter-spacing: 0.01em;">
                        Please wait a moment and then refresh if the issue persists.
                    </p>
                </div>
                """,
                unsafe_allow_html=True,
            )
        st.stop()

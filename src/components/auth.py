import ast
import io
import os
import re
from datetime import datetime
from functools import lru_cache
from urllib.parse import quote_plus

import bcrypt
import cloudinary
import cloudinary.uploader
import psycopg2
import psycopg2.extras
import streamlit as st
from typing import Optional

from src.database.connection import execute_query, get_conn_from_pool


def format_member_id(count: int) -> str:
    next_index = count + 1
    return f"CBO-{next_index:03d}"


def hash_password(password: str) -> str:
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")


def check_password(password: str, hashed: bytes | str) -> bool:
    if not password or hashed is None:
        return False

    if isinstance(hashed, memoryview):
        hashed = bytes(hashed)

    if isinstance(hashed, (bytes, bytearray)):
        raw_bytes = bytes(hashed)
        try:
            decoded_hash = raw_bytes.decode("utf-8", errors="strict").strip()
        except UnicodeDecodeError:
            decoded_hash = raw_bytes.decode("utf-8", errors="ignore").strip()
    else:
        decoded_hash = str(hashed).strip()

    if not decoded_hash:
        return False

    # Try to handle hex-encoded bcrypt hashes (120 characters = 60 bytes * 2)
    try:
        if len(decoded_hash) == 120 and all(c in '0123456789abcdefABCDEF' for c in decoded_hash):
            hashed_bytes = bytes.fromhex(decoded_hash)
            return bcrypt.checkpw(password.encode("utf-8"), hashed_bytes)
    except (ValueError, TypeError):
        pass

    if decoded_hash.startswith(("b'", 'b"', "B'", 'B"')):
        try:
            literal_value = ast.literal_eval(decoded_hash)
            if isinstance(literal_value, bytes):
                decoded_hash = literal_value.decode("utf-8", errors="ignore").strip()
        except (SyntaxError, ValueError):
            pass

    try:
        hashed_bytes = decoded_hash.encode("utf-8")
    except Exception:
        return False

    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed_bytes)
    except (ValueError, TypeError):
        return False


def register_member(full_name: str, email: str, phone: str, password: str) -> Optional[str]:
    try:
        existing = execute_query(
            "SELECT 1 AS exists_flag FROM members WHERE email = %s LIMIT 1;",
            params=(email,),
            fetch=True,
        )
        if existing:
            return None

        result = execute_query(
            "SELECT COALESCE(MAX(id), 0) AS max_id FROM members;",
            params=None,
            fetch=True,
        )
        count = int(result[0]["max_id"] or 0) if result else 0
        member_id = format_member_id(count)

        pw_hash = hash_password(password)
        execute_query(
            """
            INSERT INTO members (member_id, full_name, email, phone, password_hash, role, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            params=(member_id, full_name, email, phone, pw_hash, "Member", "Pending"),
            fetch=False,
        )
        return member_id
    except Exception as e:
        st.exception(e)
        return None


def find_member_by_identifier(identifier: str):
    try:
        select_columns = _build_member_select_columns()
        rows = execute_query(
            f"SELECT {select_columns} FROM members WHERE member_id = %s LIMIT 1;",
            params=(identifier,),
            fetch=True,
        )
        if rows:
            return rows[0]

        rows = execute_query(
            f"SELECT {select_columns} FROM members WHERE email = %s LIMIT 1;",
            params=(identifier,),
            fetch=True,
        )
        return rows[0] if rows else None
    except Exception as e:
        st.exception(e)
        return None


@lru_cache(maxsize=1)
def _load_cloudinary_config() -> bool:
    try:
        cloud_name = None
        api_key = None
        api_secret = None

        try:
            cloud_name = st.secrets.get("CLOUDINARY_CLOUD_NAME")
            api_key = st.secrets.get("CLOUDINARY_API_KEY")
            api_secret = st.secrets.get("CLOUDINARY_API_SECRET")
        except Exception:
            pass

        cloud_name = cloud_name or os.environ.get("CLOUDINARY_CLOUD_NAME")
        api_key = api_key or os.environ.get("CLOUDINARY_API_KEY")
        api_secret = api_secret or os.environ.get("CLOUDINARY_API_SECRET")

        if not all([cloud_name, api_key, api_secret]):
            return False

        cloudinary.config(
            cloud_name=cloud_name,
            api_key=api_key,
            api_secret=api_secret,
            secure=True,
        )
        return True
    except Exception:
        return False


def _find_avatar_column() -> Optional[str]:
    try:
        with get_conn_from_pool() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = %s "
                    "AND column_name = ANY(%s) "
                    "LIMIT 1;",
                    ("members", ["avatar_url", "profile_image_url", "avatar_path", "profile_photo", "profile_image"]),
                )
                row = cur.fetchone()
        return row[0] if row else None
    except Exception as exc:
        st.error(f"Avatar schema check failed: {exc}")
        return None


def _get_member_columns() -> list[str]:
    candidate_columns = [
        "id",
        "member_id",
        "full_name",
        "email",
        "phone",
        "password_hash",
        "role",
        "status",
        "join_date",
        "notes",
        "avatar_url",
        "date_of_birth",
        "gender",
        "address",
        "city",
        "country",
        "nationality",
        "occupation",
        "employer",
        "national_id",
        "next_of_kin_name",
        "next_of_kin_relationship",
        "next_of_kin_phone",
        "emergency_contact_name",
        "emergency_contact_phone",
    ]
    try:
        with get_conn_from_pool() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = %s "
                    "AND column_name = ANY(%s);",
                    ("members", candidate_columns),
                )
                rows = cur.fetchall()
        existing_columns = {row[0] for row in rows} if rows else set()
        return [col for col in candidate_columns if col in existing_columns]
    except Exception as exc:
        st.error(f"Unable to determine member profile fields: {exc}")
        return [
            "id",
            "member_id",
            "full_name",
            "email",
            "phone",
            "password_hash",
            "role",
            "status",
            "join_date",
        ]


def _ensure_avatar_column() -> Optional[str]:
    avatar_column = _find_avatar_column()
    if avatar_column:
        return avatar_column

    try:
        execute_query("ALTER TABLE members ADD COLUMN IF NOT EXISTS avatar_url TEXT;", params=None, fetch=False)
        return "avatar_url"
    except Exception as exc:
        st.error(f"Unable to create avatar_url column: {exc}")
        return None


def _build_member_select_columns() -> str:
    columns = _get_member_columns()
    if not columns:
        columns = [
            "id",
            "member_id",
            "full_name",
            "email",
            "phone",
            "password_hash",
            "role",
            "status",
            "join_date",
        ]
    return ", ".join(columns)


def get_avatar(member_id: str, full_name: Optional[str] = None) -> str:
    member = find_member_by_identifier(member_id)
    display_name = full_name or (member.get("full_name") if member else member_id)
    if member is not None:
        avatar_url = member.get("avatar_url")
        if avatar_url:
            return avatar_url

    safe_name = quote_plus(display_name or "Member")
    return f"https://ui-avatars.com/api/?name={safe_name}&background=2F80ED&color=fff&size=256"


def update_member_avatar(member_id: str, uploaded_file) -> tuple[bool, str, Optional[str]]:
    if uploaded_file is None:
        return False, "No photo was uploaded.", None

    if not _load_cloudinary_config():
        return False, (
            "Cloudinary is not configured. Please set CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET."), None

    try:
        file_bytes = uploaded_file.getbuffer()
    except Exception:
        return False, "Unable to read the uploaded file.", None

    if not file_bytes:
        return False, "Uploaded photo contains no data.", None

    safe_filename = re.sub(r"[^0-9A-Za-z._-]", "_", uploaded_file.name or "avatar.jpg")
    public_id = f"comfort_portal/avatars/{member_id}_{int(datetime.utcnow().timestamp())}_{safe_filename}"

    try:
        upload_result = cloudinary.uploader.upload(
            io.BytesIO(file_bytes),
            public_id=public_id,
            overwrite=True,
            resource_type="image",
            folder="comfort_portal/avatars",
        )
        avatar_url = upload_result.get("secure_url")
        if not avatar_url:
            raise RuntimeError("Cloudinary upload succeeded but did not return a secure URL.")
    except Exception as exc:
        return False, f"Cloudinary upload failed: {exc}", None

    avatar_column = _ensure_avatar_column()
    if not avatar_column:
        return False, (
            "No avatar field exists in the members table and it could not be created. Please verify your database schema."), avatar_url

    try:
        execute_query(
            f"UPDATE members SET {avatar_column} = %s WHERE member_id = %s;",
            params=(avatar_url, member_id),
            fetch=False,
        )
        return True, "Profile image stored in Cloudinary and synced to your record.", avatar_url
    except Exception as exc:
        return False, f"Database update failed: {exc}", avatar_url


def update_member_password(member_id: str, current_password: str, new_password: str) -> tuple[bool, str]:
    if not current_password or not new_password:
        return False, "Both current and new passwords are required."

    member = find_member_by_identifier(member_id)
    if member is None:
        return False, "Unable to locate your member profile."

    stored_hash = member.get("password_hash")
    if isinstance(stored_hash, memoryview):
        stored_hash = bytes(stored_hash)

    try:
        if not check_password(current_password, stored_hash):
            return False, "Current password is incorrect."
    except Exception:
        return False, "Unable to verify your current password."

    try:
        pw_hash = hash_password(new_password)
        execute_query(
            "UPDATE members SET password_hash = %s WHERE member_id = %s;",
            params=(pw_hash, member_id),
            fetch=False,
        )
        return True, "Password updated successfully."
    except Exception as exc:
        return False, f"Failed to update password: {exc}"


def auth_ui():
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
    if "_login_in_progress" not in st.session_state:
        st.session_state._login_in_progress = False

    left_col, right_col = st.columns(2, gap="large")

    with left_col:
        st.image("logo.png", width=120)
        st.markdown("### Comfort Portal")
        st.markdown("## Member Access")
        st.markdown("Welcome back! Sign in to continue to your Comfort Portal dashboard.")

        tabs = st.tabs(["🔑 Member Login", "📝 Register New Account"])

        # LOGIN TAB
        with tabs[0]:
            with st.form("login_form"):
                identifier = st.text_input("Member ID or Email", placeholder="MEM001 or name@example.com")
                password = st.text_input("Password", type="password")
                submitted = st.form_submit_button("Log in", disabled=st.session_state._login_in_progress)

            if submitted and not st.session_state._login_in_progress:
                st.session_state._login_in_progress = True
                if not identifier or not password:
                    st.toast("Please provide both Member ID/Email and Password.", icon="⚠️")
                    st.session_state._login_in_progress = False
                else:
                    row = find_member_by_identifier(identifier.strip())
                    if row is None:
                        st.toast("No account found with that Member ID or Email.", icon="❌")
                        st.session_state._login_in_progress = False
                    else:
                        stored_hash = bytes(row["password_hash"]) if isinstance(row["password_hash"], memoryview) else row["password_hash"]
                        try:
                            if check_password(password, stored_hash):
                                st.session_state.logged_in = True
                                st.session_state.user_id = row["member_id"]
                                st.session_state.member_id = int(row["id"])
                                st.session_state.user_name = row["full_name"]
                                st.session_state.user_role = row["role"]
                                st.session_state.user_status = row["status"]
                                st.session_state.join_date = row.get("join_date")
                                st.session_state._login_in_progress = False
                                st.toast(f"Welcome, {row['full_name']}!", icon="✅")
                                st.rerun()
                            else:
                                st.toast("Incorrect password.", icon="❌")
                                st.session_state._login_in_progress = False
                        except Exception as e:
                            st.exception(e)
                            st.session_state._login_in_progress = False

        # REGISTER TAB
        with tabs[1]:
            with st.form("register_form"):
                col1, col2 = st.columns(2)
                with col1:
                    full_name = st.text_input("Full Name")
                    email = st.text_input("Email")
                with col2:
                    phone = st.text_input("Phone Number")
                    password = st.text_input("Password", type="password")
                confirm = st.text_input("Confirm Password", type="password")

                reg_submitted = st.form_submit_button("Create Account")

            if reg_submitted:
                # basic validation
                if not full_name or not email or not phone or not password or not confirm:
                    st.toast("All fields are required.", icon="⚠️")
                elif password != confirm:
                    st.toast("Passwords do not match.", icon="⚠️")
                elif not re.match(r"[^@]+@[^@]+\.[^@]+", email):
                    st.toast("Please enter a valid email address.", icon="⚠️")
                else:
                    # attempt registration
                    member_id = register_member(full_name.strip(), email.strip().lower(), phone.strip(), password)
                    if member_id is None:
                        st.toast("Registration failed: email may already be in use.", icon="❌")
                    else:
                        st.toast(f"Account created. Your Member ID is {member_id}", icon="✅")
                        st.success(f"Registration successful — remember your Member ID: {member_id}")

    with right_col:
        st.image("logo.png", use_container_width=True)


if __name__ == "__main__":
    auth_ui()

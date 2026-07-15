import ast
import io
import json
import os
import re
from collections.abc import Mapping
from datetime import datetime, date
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


def check_password(password: str, hashed: Optional[bytes | str]) -> bool:
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

    if decoded_hash == password:
        return True

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


def _remembered_login_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".comfort_portal_remembered_login.json")


def _load_remembered_identifier() -> str:
    try:
        path = _remembered_login_path()
        if not os.path.exists(path):
            return ""

        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        identifier = data.get("identifier") if isinstance(data, dict) else None
        if isinstance(identifier, str):
            return identifier.strip()
    except Exception:
        pass
    return ""


def _ensure_member_profile_columns() -> None:
    try:
        execute_query(
            """
            CREATE TABLE IF NOT EXISTS members (
                id SERIAL PRIMARY KEY,
                member_id TEXT UNIQUE,
                full_name TEXT,
                email TEXT UNIQUE,
                phone TEXT,
                password_hash TEXT,
                role TEXT,
                status TEXT,
                join_date DATE,
                notes TEXT,
                avatar_url TEXT,
                date_of_birth DATE,
                gender TEXT,
                address TEXT,
                city TEXT,
                country TEXT,
                nationality TEXT,
                occupation TEXT,
                employer TEXT,
                national_id TEXT,
                next_of_kin_name TEXT,
                next_of_kin_relationship TEXT,
                next_of_kin_phone TEXT,
                emergency_contact_name TEXT,
                emergency_contact_phone TEXT
            );
            """,
            params=None,
            fetch=False,
        )
        execute_query(
            """
            ALTER TABLE members
            ADD COLUMN IF NOT EXISTS join_date DATE,
            ADD COLUMN IF NOT EXISTS notes TEXT,
            ADD COLUMN IF NOT EXISTS avatar_url TEXT,
            ADD COLUMN IF NOT EXISTS date_of_birth DATE,
            ADD COLUMN IF NOT EXISTS gender TEXT,
            ADD COLUMN IF NOT EXISTS address TEXT,
            ADD COLUMN IF NOT EXISTS city TEXT,
            ADD COLUMN IF NOT EXISTS country TEXT,
            ADD COLUMN IF NOT EXISTS nationality TEXT,
            ADD COLUMN IF NOT EXISTS occupation TEXT,
            ADD COLUMN IF NOT EXISTS employer TEXT,
            ADD COLUMN IF NOT EXISTS national_id TEXT,
            ADD COLUMN IF NOT EXISTS next_of_kin_name TEXT,
            ADD COLUMN IF NOT EXISTS next_of_kin_relationship TEXT,
            ADD COLUMN IF NOT EXISTS next_of_kin_phone TEXT,
            ADD COLUMN IF NOT EXISTS emergency_contact_name TEXT,
            ADD COLUMN IF NOT EXISTS emergency_contact_phone TEXT;
            """,
            params=None,
            fetch=False,
        )
    except Exception as exc:
        st.warning(f"Unable to prepare member profile fields: {exc}")


def _save_remembered_identifier(identifier: str) -> None:
    try:
        path = _remembered_login_path()
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"identifier": identifier.strip()}, handle)
    except Exception:
        pass


def _clear_remembered_identifier() -> None:
    try:
        os.remove(_remembered_login_path())
    except FileNotFoundError:
        pass
    except Exception:
        pass


def register_member(
    full_name: str,
    email: str,
    phone: str,
    password: str,
    date_of_birth: Optional[object] = None,
    gender: Optional[str] = None,
    address: Optional[str] = None,
    city: Optional[str] = None,
    country: Optional[str] = None,
    nationality: Optional[str] = None,
    occupation: Optional[str] = None,
    employer: Optional[str] = None,
    national_id: Optional[str] = None,
    next_of_kin_name: Optional[str] = None,
    next_of_kin_relationship: Optional[str] = None,
    next_of_kin_phone: Optional[str] = None,
    emergency_contact_name: Optional[str] = None,
    emergency_contact_phone: Optional[str] = None,
    notes: Optional[str] = None,
) -> Optional[str]:
    try:
        _ensure_member_profile_columns()

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
            INSERT INTO members (
                member_id,
                full_name,
                email,
                phone,
                password_hash,
                role,
                status,
                notes,
                date_of_birth,
                gender,
                address,
                city,
                country,
                nationality,
                occupation,
                employer,
                national_id,
                next_of_kin_name,
                next_of_kin_relationship,
                next_of_kin_phone,
                emergency_contact_name,
                emergency_contact_phone
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            params=(
                member_id,
                full_name,
                email,
                phone,
                pw_hash,
                "Member",
                "Pending",
                notes,
                date_of_birth,
                gender,
                address,
                city,
                country,
                nationality,
                occupation,
                employer,
                national_id,
                next_of_kin_name,
                next_of_kin_relationship,
                next_of_kin_phone,
                emergency_contact_name,
                emergency_contact_phone,
            ),
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
        _ensure_member_profile_columns()
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
        if isinstance(row, Mapping):
            return row.get("column_name")
        return None
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
        _ensure_member_profile_columns()
        with get_conn_from_pool() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = %s "
                    "AND column_name = ANY(%s);",
                    ("members", candidate_columns),
                )
                rows = cur.fetchall()
        if rows:
            existing_columns = {row.get("column_name") for row in rows if isinstance(row, Mapping) and row.get("column_name")}
        else:
            existing_columns = set()
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
    if "remember_me" not in st.session_state:
        st.session_state.remember_me = bool(_load_remembered_identifier())

    st.markdown(
        """
        <style>
        @media (max-width: 768px) {
          div[data-testid="stHorizontalBlock"] {
            flex-wrap: wrap !important;
          }
          div[data-testid="stHorizontalBlock"] > div {
            width: 100% !important;
            min-width: 100% !important;
            max-width: 100% !important;
            padding: 0 !important;
            margin: 0 !important;
          }
          div[data-testid="stHorizontalBlock"] > div > div {
            width: 100% !important;
          }
          .block-container {
            max-width: 100% !important;
            padding-left: 0.8rem !important;
            padding-right: 0.8rem !important;
          }
          [data-testid="stAppViewContainer"] {
            padding-left: 0 !important;
            padding-right: 0 !important;
          }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    left_col, right_col = st.columns(2, gap="large")

    with left_col:
        st.image("logo.png", width=120)
        st.markdown("### Comfort Portal")
        st.markdown("## Member Access")
        st.markdown("Welcome back! Sign in to continue to your Comfort Portal dashboard.")

        tabs = st.tabs(["🔑 Member Login", "📝 Register New Account"])

        # LOGIN TAB
        with tabs[0]:
            remembered_identifier = _load_remembered_identifier()
            with st.form("login_form"):
                identifier = st.text_input(
                    "Member ID or Email",
                    value=remembered_identifier,
                    placeholder="CBO-001 or name@example.com",
                )
                password = st.text_input("Password", type="password")
                remember_me = st.checkbox(
                    "Remember me on this device",
                    value=bool(remembered_identifier),
                    help="This saves your Member ID/email so it is ready next time.",
                )
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
                                if remember_me:
                                    _save_remembered_identifier(identifier.strip())
                                else:
                                    _clear_remembered_identifier()
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
                st.markdown("### Personal Information")
                col1, col2 = st.columns(2)
                with col1:
                    full_name = st.text_input("Full Name")
                    email = st.text_input("Email")
                    phone = st.text_input("Phone Number")
                    date_of_birth = st.date_input(
                        "Date of Birth",
                        value=None,
                        min_value=date(1964, 1, 1),
                        max_value=date(2024, 12, 31),
                    )
                    gender = st.selectbox("Gender", ["", "Male", "Female", "Other", "Prefer not to say"], index=0)
                    address = st.text_input("Address")
                    city = st.text_input("City")
                with col2:
                    country = st.text_input("Country")
                    nationality = st.text_input("Nationality")
                    occupation = st.text_input("Occupation")
                    employer = st.text_input("Employer")
                    national_id = st.text_input("National ID")
                    next_of_kin_name = st.text_input("Next of Kin Name")
                    next_of_kin_relationship = st.text_input("Next of Kin Relationship")
                    next_of_kin_phone = st.text_input("Next of Kin Phone")
                emergency_contact_name = st.text_input("Emergency Contact Name")
                emergency_contact_phone = st.text_input("Emergency Contact Phone")
                notes = st.text_area("Notes")

                st.markdown("### Account Security")
                password = st.text_input("Password", type="password")
                confirm = st.text_input("Confirm Password", type="password")

                reg_submitted = st.form_submit_button("Create Account")

            if reg_submitted:
                # basic validation
                if not full_name or not email or not phone or not password or not confirm:
                    st.toast("Please complete all required fields.", icon="⚠️")
                elif password != confirm:
                    st.toast("Passwords do not match.", icon="⚠️")
                elif not re.match(r"[^@]+@[^@]+\.[^@]+", email):
                    st.toast("Please enter a valid email address.", icon="⚠️")
                else:
                    # attempt registration
                    member_id = register_member(
                        full_name.strip(),
                        email.strip().lower(),
                        phone.strip(),
                        password,
                        date_of_birth=date_of_birth,
                        gender=gender.strip() or None,
                        address=address.strip() or None,
                        city=city.strip() or None,
                        country=country.strip() or None,
                        nationality=nationality.strip() or None,
                        occupation=occupation.strip() or None,
                        employer=employer.strip() or None,
                        national_id=national_id.strip() or None,
                        next_of_kin_name=next_of_kin_name.strip() or None,
                        next_of_kin_relationship=next_of_kin_relationship.strip() or None,
                        next_of_kin_phone=next_of_kin_phone.strip() or None,
                        emergency_contact_name=emergency_contact_name.strip() or None,
                        emergency_contact_phone=emergency_contact_phone.strip() or None,
                        notes=notes.strip() or None,
                    )
                    if member_id is None:
                        st.toast("Registration failed: email may already be in use.", icon="❌")
                    else:
                        st.toast(f"Account created. Your Member ID is {member_id}", icon="✅")
                        st.success(f"Registration successful — remember your Member ID: {member_id}")

    with right_col:
        st.image("logo.png", width='stretch')


if __name__ == "__main__":
    auth_ui()

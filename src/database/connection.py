import contextlib
import logging
import os
import socket
from typing import Any, Iterable, Iterator, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import psycopg2
import psycopg2.extras
import streamlit as st


class DatabaseUnavailableError(Exception):
    """Raised when the database connection cannot be established or acquired from the pool."""
    pass


logger = logging.getLogger(__name__)


def _normalize_dsn(dsn: str) -> str:
    """Add connection-timeout and SSL settings to a PostgreSQL DSN when missing."""

    if not dsn:
        return dsn

    if "://" in dsn:
        parsed = urlparse(dsn)
        if parsed.scheme.startswith("postgres"):
            query = dict(parse_qsl(parsed.query, keep_blank_values=True))
            query.setdefault("sslmode", "require")
            query.setdefault("connect_timeout", "10")
            parsed = parsed._replace(query=urlencode(query))
            return urlunparse(parsed)
        return dsn

    return dsn + " sslmode=require connect_timeout=10"


def _resolve_db_dsn() -> str:
    """
    Resolve the PostgreSQL DSN.

    Priority:
    1. Streamlit secrets DATABASE_URL
    2. Streamlit secrets DB_URL
    3. Environment DATABASE_URL
    4. Environment DB_URL
    5. Individual DB_* environment variables
    """

    db_url = None
    host: Optional[str] = None

    try:
        db_url = (
            st.secrets.get("DATABASE_URL")
            or st.secrets.get("DB_URL")
        )
    except Exception:
        pass

    db_url = (
        db_url
        or os.getenv("DATABASE_URL")
        or os.getenv("DB_URL")
    )

    if db_url:
        normalized_dsn = _normalize_dsn(str(db_url))
        try:
            parsed = urlparse(normalized_dsn)
            host = parsed.hostname
            if not host:
                raise DatabaseUnavailableError(
                    "Unable to resolve the database hostname. Check Neon pooler URL and secrets configuration."
                )
            socket.gethostbyname(host)
            return normalized_dsn
        except socket.gaierror as exc:
            logger.error(
                "Database hostname could not be resolved for %s. Check Neon pooler URL and secrets configuration.",
                host or "<unknown>",
            )
            raise DatabaseUnavailableError(
                "Unable to resolve the database hostname. Check Neon pooler URL and secrets configuration."
            ) from exc
        except DatabaseUnavailableError:
            raise
        except Exception as exc:
            logger.error("Unable to validate database connection settings: %s", exc)
            raise DatabaseUnavailableError(
                "Unable to resolve the database hostname. Check Neon pooler URL and secrets configuration."
            ) from exc

    host = os.getenv("DB_HOST") or ""
    dbname = os.getenv("DB_NAME")
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD") or os.getenv("DB_PASS")
    port = os.getenv("DB_PORT", "5432")

    missing = [
        key
        for key, value in {
            "DB_HOST": host,
            "DB_NAME": dbname,
            "DB_USER": user,
            "DB_PASSWORD": password,
        }.items()
        if not value
    ]
    if missing:
        raise DatabaseUnavailableError(
            "Missing required database settings: "
            f"{', '.join(missing)}. Check Neon pooler URL and secrets configuration."
        )

    return _normalize_dsn(
        f"host={host} "
        f"dbname={dbname} "
        f"user={user} "
        f"password={password} "
        f"port={port}"
    )


@st.cache_resource
def init_db_pool(
    minconn: int = 1,
    maxconn: int = 5,
):
    """
    Create and reuse one PostgreSQL connection for the entire Streamlit app.
    """

    last_error = None
    for attempt in range(1, 4):
        try:
            dsn = _resolve_db_dsn()
            conn = psycopg2.connect(
                dsn,
                cursor_factory=psycopg2.extras.RealDictCursor,
                connect_timeout=10,
                sslmode="require",
            )
            conn.autocommit = False
            return conn
        except socket.gaierror as exc:
            last_error = exc
            logger.warning(
                "DNS resolution failed while creating the database connection (attempt %s/3): %s",
                attempt,
                exc,
            )
            if attempt == 3:
                raise DatabaseUnavailableError(
                    "Unable to resolve the database hostname. Check Neon pooler URL and secrets configuration."
                ) from exc
        except Exception as exc:
            last_error = exc
            logger.exception("Unable to create database connection (attempt %s/3).", attempt)
            if attempt == 3:
                raise DatabaseUnavailableError(
                    "Unable to connect to the database. Check Neon pooler URL and secrets configuration."
                ) from exc

    if last_error:
        raise DatabaseUnavailableError(
            "Unable to connect to the database. Check Neon pooler URL and secrets configuration."
        ) from last_error

    raise DatabaseUnavailableError(
        "Unable to connect to the database. Check Neon pooler URL and secrets configuration."
    )


def clear_cached_connection() -> None:
    """Clear the cached psycopg2 connection so a fresh connection can be created."""

    try:
        if hasattr(init_db_pool, "clear"):
            init_db_pool.clear()
    except Exception:
        logger.exception("Unable to clear cached database connection.")


def _normalize_params(
    params: Optional[Iterable[Any]],
) -> Optional[Tuple[Any, ...]]:
    if params is None:
        return None

    try:
        return tuple(params)
    except TypeError:
        return (params,)


def _is_connection_usable(conn) -> bool:
    if conn is None or getattr(conn, "closed", False):
        return False

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return True
    except (psycopg2.InterfaceError, psycopg2.OperationalError, psycopg2.DatabaseError):
        return False


@contextlib.contextmanager
def get_conn_from_pool() -> Iterator[psycopg2.extensions.connection]:
    """
    Yield the shared cached database connection.
    """

    conn: Optional[psycopg2.extensions.connection] = None
    try:
        conn = init_db_pool()
        if not _is_connection_usable(conn):
            logger.warning("Cached connection is unavailable or invalid. Rebuilding it.")
            clear_cached_connection()
            conn = init_db_pool()
        yield conn
    finally:
        if conn is not None and not conn.closed:
            try:
                conn.rollback()
            except Exception:
                logger.exception("Failed to rollback database connection.")


def _execute_on_connection(
    conn,
    query: str,
    params: Optional[Iterable[Any]],
    fetch: bool,
):
    normalized = _normalize_params(params)

    with conn.cursor(
        cursor_factory=psycopg2.extras.RealDictCursor
    ) as cur:

        cur.execute(query, normalized)

        is_select = query.lstrip().upper().startswith(("SELECT", "WITH"))

        if fetch:
            rows = cur.fetchall()
            if not is_select:
                conn.commit()
            else:
                conn.rollback()
            return [dict(r) for r in rows]

        conn.commit()
        return None


def execute_query(
    query: str,
    params: Optional[Iterable[Any]] = None,
    fetch: bool = False,
) -> Optional[List[dict]]:
    """
    Execute SQL safely using the shared cached connection.
    Retries up to three times on transient connection failures.
    """

    last_error = None
    is_write = not fetch and not query.lstrip().upper().startswith(("SELECT", "WITH"))

    for attempt in range(1, 4):
        try:
            with get_conn_from_pool() as conn:
                try:
                    result = _execute_on_connection(
                        conn,
                        query,
                        params,
                        fetch,
                    )
                    if is_write:
                        clear_query_cache()
                    return result
                except (
                    psycopg2.InterfaceError,
                    psycopg2.OperationalError,
                    psycopg2.DatabaseError,
                ) as exc:
                    logger.warning(
                        "Transient database error during query execution (attempt %s/3): %s",
                        attempt,
                        exc,
                    )
                    last_error = exc
                    try:
                        conn.close()
                    except Exception:
                        pass
                    clear_cached_connection()
                    if attempt == 3:
                        raise
                    continue
        except (
            psycopg2.InterfaceError,
            psycopg2.OperationalError,
            psycopg2.DatabaseError,
            DatabaseUnavailableError,
        ) as exc:
            logger.warning(
                "Transient database error while acquiring connection (attempt %s/3): %s",
                attempt,
                exc,
            )
            last_error = exc
            clear_cached_connection()
            if attempt == 3:
                raise
            continue
        except Exception:
            logger.exception("Database query failed.")
            raise

    if last_error:
        raise last_error

    return None


@st.cache_data(ttl=300, show_spinner=False)
def cached_read_query(
    query: str,
    params: Optional[Iterable[Any]] = None,
) -> List[dict]:
    """
    Cache read-only SELECT queries for five minutes.
    """

    upper = query.strip().upper()

    if not (
        upper.startswith("SELECT")
        or upper.startswith("WITH")
    ):
        raise ValueError(
            "cached_read_query() only supports SELECT/WITH queries."
        )

    return execute_query(
        query,
        params=params,
        fetch=True,
    ) or []


def clear_query_cache():
    """
    Clear Streamlit read cache after writes.
    """

    try:
        if hasattr(cached_read_query, "clear"):
            cached_read_query.clear()
    except Exception:
        logger.exception("Unable to clear cached queries.")


def close_pool():
    """
    Close the cached connection.
    """

    try:
        conn = init_db_pool()
        if conn is not None and not conn.closed:
            conn.close()
    except Exception:
        logger.exception("Failed closing database connection.")

    clear_cached_connection()
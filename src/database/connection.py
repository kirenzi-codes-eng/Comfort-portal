import contextlib
import logging
import os
from typing import Any, Iterable, List, Optional, Tuple

import psycopg2
import psycopg2.extras
from psycopg2.pool import SimpleConnectionPool
import streamlit as st


class DatabaseUnavailableError(RuntimeError):
    """Raised when the application cannot establish a database connection."""
    pass


logger = logging.getLogger(__name__)


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
        return db_url

    host = os.getenv("DB_HOST")
    dbname = os.getenv("DB_NAME")
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD") or os.getenv("DB_PASS")
    port = os.getenv("DB_PORT", "5432")

    if not all([host, dbname, user, password]):
        raise RuntimeError(
            "Database configuration not found.\n"
            "Expected DATABASE_URL (preferred), DB_URL, or DB_HOST/DB_NAME/DB_USER/DB_PASSWORD."
        )

    return (
        f"host={host} "
        f"dbname={dbname} "
        f"user={user} "
        f"password={password} "
        f"port={port} "
        f"sslmode=require"
    )


@st.cache_resource
def init_db_pool(
    minconn: int = 1,
    maxconn: int = 5,
) -> SimpleConnectionPool:
    """
    Create one PostgreSQL connection pool for the entire Streamlit app.
    """

    dsn = _resolve_db_dsn()

    try:
        return SimpleConnectionPool(
            minconn=minconn,
            maxconn=maxconn,
            dsn=dsn,
        )
    except Exception as exc:
        logger.exception("Unable to create database connection pool.")
        raise DatabaseUnavailableError(
            "Unable to create a database connection pool. Verify database credentials and network connectivity."
        ) from exc


def _normalize_params(
    params: Optional[Iterable[Any]],
) -> Optional[Tuple[Any, ...]]:
    if params is None:
        return None

    try:
        return tuple(params)
    except TypeError:
        return (params,)


@contextlib.contextmanager
def get_conn_from_pool():
    """
    Borrow a connection from the pool.
    """

    pool = init_db_pool()
    conn = None

    try:
        try:
            conn = pool.getconn()
        except (
            psycopg2.InterfaceError,
            psycopg2.OperationalError,
            psycopg2.DatabaseError,
        ) as exc:
            logger.exception("Unable to acquire database connection from pool.")
            raise DatabaseUnavailableError(
                "Unable to connect to the database. Check your DB host, credentials, and network."
            ) from exc

        if conn.closed:
            logger.warning("Discarding closed connection.")
            pool.putconn(conn, close=True)
            try:
                conn = psycopg2.connect(
                    _resolve_db_dsn(),
                    cursor_factory=psycopg2.extras.RealDictCursor,
                )
            except Exception as exc:
                logger.exception("Unable to open fallback database connection.")
                raise DatabaseUnavailableError(
                    "Unable to establish a fallback database connection. Verify database host and network."
                ) from exc

        yield conn

    finally:
        if conn is not None:
            try:
                if conn.closed:
                    pool.putconn(conn, close=True)
                else:
                    pool.putconn(conn)
            except Exception:
                logger.exception("Failed returning connection to pool.")


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
            return [dict(r) for r in rows]

        conn.commit()
        return None


def execute_query(
    query: str,
    params: Optional[Iterable[Any]] = None,
    fetch: bool = False,
) -> Optional[List[dict]]:
    """
    Execute SQL safely using the shared connection pool.
    Retries once on transient connection failures.
    """

    last_error = None

    for _ in range(2):
        try:
            with get_conn_from_pool() as conn:
                try:
                    return _execute_on_connection(
                        conn,
                        query,
                        params,
                        fetch,
                    )
                except (
                    psycopg2.InterfaceError,
                    psycopg2.OperationalError,
                ) as exc:
                    logger.exception(
                        "Transient database error during query execution. Retrying once."
                    )
                    last_error = exc
                    try:
                        conn.close()
                    except Exception:
                        pass
                    continue
        except (
            psycopg2.InterfaceError,
            psycopg2.OperationalError,
            DatabaseUnavailableError,
        ) as exc:
            logger.exception("Transient database error while acquiring connection. Retrying once.")
            last_error = exc
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
        cached_read_query.clear()
    except Exception:
        logger.exception("Unable to clear cached queries.")


def close_pool():
    """
    Close every connection in the pool.
    """

    try:
        pool = init_db_pool()
        pool.closeall()
    except Exception:
        logger.exception("Failed closing connection pool.")

    try:
        init_db_pool.clear()
    except Exception:
        pass
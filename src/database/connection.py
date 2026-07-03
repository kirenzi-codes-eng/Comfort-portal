import logging
import os
import contextlib
from typing import Any, Iterable, List, Optional

import psycopg2
import psycopg2.extras
from psycopg2.pool import SimpleConnectionPool
import streamlit as st


logger = logging.getLogger(__name__)


@st.cache_resource(ttl=600)
def init_db_pool(minconn: int = 1, maxconn: int = 5) -> SimpleConnectionPool:
    """Initialize and cache a single SimpleConnectionPool for the app lifecycle.

    It prefers `st.secrets["DATABASE_URL"]` but will fall back to the
    `DATABASE_URL` environment variable or component env vars if needed.
    """
    db_url = None
    try:
        db_url = st.secrets.get("DATABASE_URL")  # type: ignore
    except Exception:
        # st.secrets may not be set in some contexts
        db_url = None

    db_url = db_url or os.environ.get("DATABASE_URL")

    if not db_url:
        host = os.environ.get("DB_HOST")
        dbname = os.environ.get("DB_NAME")
        user = os.environ.get("DB_USER")
        password = os.environ.get("DB_PASSWORD") or os.environ.get("DB_PASS")
        port = os.environ.get("DB_PORT", "5432")
        if not all([host, dbname, user, password]):
            raise RuntimeError("Database configuration not found in st.secrets or environment variables")
        dsn = f"host={host} dbname={dbname} user={user} password={password} port={port} sslmode=require"
    else:
        dsn = db_url

    try:
        pool = SimpleConnectionPool(minconn=minconn, maxconn=maxconn, dsn=dsn)
        return pool
    except Exception as exc:
        logger.exception("Failed to create DB connection pool: %s", exc)
        raise


@contextlib.contextmanager
def get_conn_from_pool():
    """Context manager to borrow and return a connection from the cached pool."""
    pool = init_db_pool()
    conn = None
    try:
        conn = pool.getconn()
        yield conn
    except Exception:
        logger.exception("Error while getting connection from pool")
        raise
    finally:
        if conn is not None:
            try:
                pool.putconn(conn)
            except Exception:
                logger.exception("Failed to return connection to pool")


def _discard_connection(pool: SimpleConnectionPool, conn) -> None:
    try:
        pool.putconn(conn, close=True)
    except Exception:
        logger.exception("Failed to discard broken connection")


def _reset_db_pool() -> SimpleConnectionPool:
    """Close the current pool and reinitialize the cached connection pool."""
    try:
        pool = init_db_pool()
        pool.closeall()
    except Exception:
        logger.exception("Failed to close existing DB pool during reset")

    if hasattr(init_db_pool, "clear"):
        try:
            init_db_pool.clear()
        except Exception:
            logger.exception("Failed to clear cached DB pool")

    return init_db_pool()


def _execute_on_connection(conn, query: str, params: Optional[Iterable[Any]], fetch: bool):
    query_start = (query or "").lstrip().upper()
    is_select_query = query_start.startswith("SELECT") or query_start.startswith("WITH")

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(query, params)
        if fetch and is_select_query:
            rows = cur.fetchall()
            return [dict(r) for r in rows]

        if fetch and not is_select_query:
            rows = cur.fetchall()
            conn.commit()
            return [dict(r) for r in rows]

        conn.commit()
        return None


def execute_query(query: str, params: Optional[Iterable[Any]] = None, fetch: bool = False) -> Optional[List[dict]]:
    """Execute a SQL statement safely using a connection from the pool.

    - Uses parameterized queries to avoid SQL injection.
    - Commits transactions for non-select statements.
    - Returns fetched rows as list of dicts when `fetch=True`.
    - Automatically discards broken connections and retries once with a fresh pool.
    """
    pool = init_db_pool()
    last_exc = None

    for attempt in range(2):
        conn = None
        try:
            conn = pool.getconn()
            if getattr(conn, "closed", 0):
                logger.warning("Discarding closed connection and retrying query")
                _discard_connection(pool, conn)
                conn = None
                pool = _reset_db_pool()
                continue

            return _execute_on_connection(conn, query, params, fetch)
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as db_exc:
            last_exc = db_exc
            logger.exception("Operational error executing query, discarding broken connection and retrying once: %s | params=%s", db_exc, params)
            if conn is not None:
                _discard_connection(pool, conn)
                conn = None
            if hasattr(init_db_pool, "clear"):
                try:
                    init_db_pool.clear()
                except Exception:
                    logger.exception("Failed to clear cached DB pool after operational error")
            pool = _reset_db_pool()
            continue
        except psycopg2.DatabaseError as db_exc:
            last_exc = db_exc
            if conn is not None and getattr(conn, "closed", 0):
                logger.exception("Database error on closed connection, discarding and retrying: %s | params=%s", db_exc, params)
                _discard_connection(pool, conn)
                conn = None
                pool = _reset_db_pool()
                continue
            logger.exception("Database error executing query: %s | params=%s", db_exc, params)
            raise
        except Exception as exc:
            last_exc = exc
            logger.exception("Unexpected error executing query: %s", exc)
            raise
        finally:
            if conn is not None:
                try:
                    if getattr(conn, "closed", 0):
                        pool.putconn(conn, close=True)
                    else:
                        pool.putconn(conn)
                except Exception:
                    logger.exception("Failed to return connection to pool")

    if last_exc is not None:
        raise last_exc
    return None


def close_pool():
    """Close all connections in the pool (useful during app shutdown or tests)."""
    try:
        pool = init_db_pool()
        pool.closeall()
    except Exception:
        logger.exception("Failed to close DB pool")

import contextlib
import logging
import os
import socket
from typing import Any, Generator, Iterable, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import psycopg2
import psycopg2.extras
import psycopg2.pool
import streamlit as st


# ===== Custom Exception Classes for Error Categorization =====

class DatabaseUnavailableError(Exception):
    """Base exception for database unavailability. Never expose to users directly."""
    
    def __init__(self, message: str, is_network_error: bool = False, is_temporary: bool = True):
        super().__init__(message)
        self.is_network_error = is_network_error
        self.is_temporary = is_temporary
        self.user_friendly_message = self._build_user_message()
    
    def _build_user_message(self) -> str:
        """Build a user-friendly message based on error type."""
        if self.is_network_error:
            return (
                "We're having trouble reaching the database server. Please check your internet connection and try again later."
            )
        elif self.is_temporary:
            return (
                "We're having trouble connecting to the database. Please try again later. "
                "We're temporarily unable to connect to our secure server. "
                "This is usually caused by a temporary internet or server connection issue."
            )
        else:
            return (
                "We encountered an unexpected issue while connecting to our server. Please try again. "
                "If this continues, please contact our support team."
            )


class NetworkConnectionError(DatabaseUnavailableError):
    """Raised when network connectivity issues prevent database connection."""
    
    def __init__(self, message: str = "Network connection error"):
        super().__init__(message, is_network_error=True, is_temporary=True)


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
                logger.error("Database configuration error: unable to resolve hostname from DSN")
                raise DatabaseUnavailableError(
                    "Database configuration error",
                    is_network_error=False,
                    is_temporary=False
                )
            socket.gethostbyname(host)
            return normalized_dsn
        except socket.gaierror as exc:
            logger.error(
                "Network error: database hostname could not be resolved for %s (DNS failure)",
                host or "<unknown>",
            )
            raise NetworkConnectionError(
                f"DNS resolution failed for database host"
            ) from exc
        except DatabaseUnavailableError:
            raise
        except Exception as exc:
            logger.exception("Unexpected error while validating database connection settings")
            raise DatabaseUnavailableError(
                "Unexpected database configuration error",
                is_network_error=False,
                is_temporary=False
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
    Create and reuse a PostgreSQL connection pool for the Streamlit app.
    Retries up to 3 times on transient errors before raising.
    """

    last_error = None
    for attempt in range(1, 4):
        try:
            dsn = _resolve_db_dsn()
            pool = psycopg2.pool.SimpleConnectionPool(
                minconn=minconn,
                maxconn=maxconn,
                dsn=dsn,
                connect_timeout=10,
                sslmode="require",
            )
            logger.info("Database connection pool initialized successfully")
            return pool
        except socket.gaierror as exc:
            last_error = exc
            is_last_attempt = attempt == 3
            log_level = logging.ERROR if is_last_attempt else logging.WARNING
            logger.log(
                log_level,
                "Network error: DNS resolution failed (attempt %s/3). Retrying...",
                attempt,
            )
            if is_last_attempt:
                raise NetworkConnectionError(
                    "Unable to reach the database server. Please check your internet connection."
                ) from exc
        except (psycopg2.OperationalError, psycopg2.DatabaseError) as exc:
            last_error = exc
            is_last_attempt = attempt == 3
            log_level = logging.ERROR if is_last_attempt else logging.WARNING
            error_msg = str(exc).lower()

            is_likely_temporary = any(
                keyword in error_msg
                for keyword in [
                    "timeout",
                    "connection refused",
                    "could not translate",
                    "server",
                    "unavailable",
                    "pool",
                ]
            )

            logger.log(
                log_level,
                "Database connection error (attempt %s/3, temporary=%s): %s",
                attempt,
                is_likely_temporary,
                exc,
            )

            if is_last_attempt:
                raise DatabaseUnavailableError(
                    "Unable to connect to the database server",
                    is_network_error=False,
                    is_temporary=is_likely_temporary,
                ) from exc
        except Exception as exc:
            last_error = exc
            is_last_attempt = attempt == 3
            log_level = logging.ERROR if is_last_attempt else logging.WARNING
            logger.log(
                log_level,
                "Unexpected error while creating database connection pool (attempt %s/3): %s",
                attempt,
                exc,
            )
            if is_last_attempt:
                raise DatabaseUnavailableError(
                    "Unexpected error connecting to database",
                    is_network_error=False,
                    is_temporary=False,
                ) from exc

    if last_error:
        raise DatabaseUnavailableError(
            "Unable to establish database connection after multiple attempts",
            is_network_error=False,
            is_temporary=True,
        ) from last_error

    raise DatabaseUnavailableError(
        "Unable to establish database connection",
        is_network_error=False,
        is_temporary=True,
    )


def clear_cached_connection() -> None:
    """Clear the cached connection pool so a fresh pool can be created."""

    try:
        if hasattr(init_db_pool, "clear"):
            init_db_pool.clear()
    except Exception:
        logger.exception("Unable to clear cached database connection pool.")


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


def _raise_friendly_database_error(exc: Exception, *, is_temporary: bool = True) -> None:
    logger.error("Database operation failed: %s", exc, exc_info=True)
    raise DatabaseUnavailableError(
        "We're having trouble connecting to the database. Please try again later.",
        is_network_error=False,
        is_temporary=is_temporary,
    ) from exc


@contextlib.contextmanager
def get_conn_from_pool() -> Generator[psycopg2.extensions.connection, None, None]:
    """
    Yield a connection from the shared cached pool and always return it to the pool.
    """

    pool = init_db_pool()
    conn: Optional[psycopg2.extensions.connection] = None
    try:
        conn = pool.getconn()
        if conn is None:
            raise DatabaseUnavailableError(
                "We're having trouble connecting to the database. Please try again later.",
                is_network_error=False,
                is_temporary=True,
            )
        if not _is_connection_usable(conn):
            logger.warning("Cached connection is unavailable or invalid. Rebuilding the pool.")
            try:
                pool.putconn(conn, close=True)
            except Exception:
                logger.error("Failed to discard invalid database connection from pool.", exc_info=True)
            clear_cached_connection()
            pool = init_db_pool()
            conn = pool.getconn()
            if conn is None:
                raise DatabaseUnavailableError(
                    "We're having trouble connecting to the database. Please try again later.",
                    is_network_error=False,
                    is_temporary=True,
                )

        yield conn
    finally:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                logger.error("Failed to rollback database connection.", exc_info=True)
            try:
                pool.putconn(conn)
            except Exception:
                logger.error("Failed to return database connection to pool.", exc_info=True)


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
    
    Raises:
        DatabaseUnavailableError: If unable to execute query after 3 retries.
                                  Contains categorization info (network, temporary, unexpected).
        Never exposes raw SQL errors or internal config to calling code.
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
                    error_msg = str(exc).lower()
                    is_likely_temporary = any(
                        keyword in error_msg
                        for keyword in [
                            "timeout",
                            "connection refused",
                            "idle",
                            "statement timeout",
                            "pool",
                            "server",
                        ]
                    )

                    is_last_attempt = attempt == 3
                    logger.error(
                        "Transient database error during query (attempt %s/3, temp=%s): %s",
                        attempt,
                        is_likely_temporary,
                        exc,
                        exc_info=True,
                    )
                    last_error = exc
                    clear_cached_connection()
                    if attempt == 3:
                        _raise_friendly_database_error(exc, is_temporary=is_likely_temporary)
                    continue
        except (
            psycopg2.InterfaceError,
            psycopg2.OperationalError,
            psycopg2.DatabaseError,
        ) as exc:
            error_msg = str(exc).lower()
            is_likely_temporary = any(keyword in error_msg for keyword in [
                "timeout", "connection refused", "idle", "pool", "server"
            ])

            logger.error(
                "Database connection error during query (attempt %s/3, temp=%s): %s",
                attempt,
                is_likely_temporary,
                exc,
                exc_info=True,
            )
            last_error = exc
            clear_cached_connection()
            if attempt == 3:
                _raise_friendly_database_error(exc, is_temporary=is_likely_temporary)
            continue
        except DatabaseUnavailableError:
            raise
        except Exception as exc:
            logger.error(
                "Unexpected error during database query (attempt %s/3): %s",
                attempt,
                exc,
                exc_info=True,
            )
            last_error = exc
            clear_cached_connection()
            if attempt == 3:
                _raise_friendly_database_error(exc, is_temporary=False)
            continue

    if last_error:
        raise DatabaseUnavailableError(
            "Unable to complete database operation after multiple attempts",
            is_network_error=False,
            is_temporary=True
        ) from last_error

    raise DatabaseUnavailableError(
        "Unable to complete database operation",
        is_network_error=False,
        is_temporary=True
    )


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
    Close all cached database connections.
    """

    try:
        pool = init_db_pool()
        if pool is not None and not getattr(pool, "closed", False):
            pool.closeall()
    except Exception:
        logger.error("Failed closing database connection pool.", exc_info=True)

    clear_cached_connection()
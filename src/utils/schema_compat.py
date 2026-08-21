from __future__ import annotations

import logging
from functools import lru_cache
from typing import Optional

from src.database.connection import execute_query

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_schema_catalog() -> dict[str, set[str]]:
    """Cache schema metadata for optional tables and columns used by reminder features."""
    catalog: dict[str, set[str]] = {}
    try:
        rows = execute_query(
            """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = CURRENT_SCHEMA()
            ORDER BY table_name, column_name;
            """,
            params=None,
            fetch=True,
        ) or []
    except Exception as exc:
        logger.info("Schema compatibility discovery unavailable: %s", exc)
        return catalog

    for row in rows:
        table_name = str(row.get("table_name") or "")
        column_name = str(row.get("column_name") or "")
        if not table_name or not column_name:
            continue
        catalog.setdefault(table_name.lower(), set()).add(column_name.lower())
    return catalog


def table_exists(table_name: str) -> bool:
    return table_name.lower() in get_schema_catalog()


def column_exists(table_name: str, column_name: str) -> bool:
    return column_name.lower() in get_schema_catalog().get(table_name.lower(), set())


def has_optional_feature(table_name: str, required_columns: Optional[list[str]] = None) -> bool:
    if not table_exists(table_name):
        return False
    if required_columns:
        return all(column_exists(table_name, column) for column in required_columns)
    return True

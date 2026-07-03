#!/usr/bin/env python
"""Verify avatar_url column was added to members table."""
import sys
sys.path.insert(0, ".")

from src.database.connection import get_conn_from_pool

with get_conn_from_pool() as conn:
    cur = conn.cursor()
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='members' AND column_name='avatar_url';"
    )
    result = cur.fetchone()
    if result:
        print("✓ avatar_url column confirmed in members table")
    else:
        print("✗ Column not found")
    cur.close()

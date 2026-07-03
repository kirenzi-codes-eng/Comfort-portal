#!/usr/bin/env python
"""Add avatar_url column to members table if it doesn't exist."""
import os
import sys

sys.path.insert(0, ".")

import psycopg2

from src.database.connection import get_conn_from_pool

try:
    with get_conn_from_pool() as conn:
        cur = conn.cursor()

        # Check if avatar_url column already exists
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='members' AND column_name='avatar_url';"
        )
        exists = cur.fetchone()

        if exists:
            print("✓ avatar_url column already exists in members table")
        else:
            # Add the avatar_url column
            cur.execute("ALTER TABLE members ADD COLUMN avatar_url TEXT DEFAULT NULL;")
            conn.commit()
            print("✓ Successfully added avatar_url column to members table")

        cur.close()
except Exception as e:
    print(f"✗ Error: {e}")
    sys.exit(1)

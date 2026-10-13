from __future__ import annotations

from backend.snowflake_database import SnowflakeDatabase


def get_database(db_path: str | None = None) -> SnowflakeDatabase:
    """Return the Snowflake-backed database implementation."""
    del db_path
    return SnowflakeDatabase()

from __future__ import annotations

"""
Snowflake connection management with pooling, retry logic, and session-level
performance tuning.

Usage:
    from backend.snowflake_config import get_connection, snowflake_config

    with get_connection() as conn:
        cursor = conn.cursor(snowflake.connector.DictCursor)
        cursor.execute("SELECT ...")
"""

import logging
import os
import queue
import threading
import time
from contextlib import contextmanager

import snowflake.connector
from snowflake.connector.errors import (
    DatabaseError,
    OperationalError,
    ProgrammingError,
)

logger = logging.getLogger(__name__)


def quote_snowflake_identifier(name: str) -> str:
    """Double-quote a Snowflake identifier (preserves case, escapes special chars)."""
    return '"' + name.replace('"', '""') + '"'


def auto_provision_enabled() -> bool:
    """When true, CREATE WAREHOUSE/DATABASE/SCHEMA IF NOT EXISTS before USE (dev-friendly)."""
    return os.getenv("SNOWFLAKE_AUTO_PROVISION", "true").lower() in (
        "1",
        "true",
        "yes",
    )


TRANSIENT_ERROR_CODES = {
    250001,  # connection lost
    250002,  # network error
    250003,  # request timeout
    390114,  # warehouse suspended / resuming
}


class SnowflakeConfig:
    """Reads SNOWFLAKE_* from the environment (refreshed on validate / new connections)."""

    def __init__(self):
        self.refresh_from_env()

    def refresh_from_env(self) -> None:
        self.account = os.getenv("SNOWFLAKE_ACCOUNT", "").strip()
        self.user = os.getenv("SNOWFLAKE_USER", "").strip()
        self.password = os.getenv("SNOWFLAKE_PASSWORD", "").strip()
        self.warehouse = os.getenv("SNOWFLAKE_WAREHOUSE", "").strip()
        self.database = os.getenv("SNOWFLAKE_DATABASE", "").strip()
        self.schema = os.getenv("SNOWFLAKE_SCHEMA", "").strip()
        self.pool_size = int(os.getenv("SNOWFLAKE_CONNECTION_POOL_SIZE", "10"))
        self.query_timeout = int(os.getenv("SNOWFLAKE_QUERY_TIMEOUT", "300"))

    @property
    def connect_kwargs(self) -> dict:
        """Full connection (use only after warehouse/database/schema exist)."""
        return {
            "account": self.account,
            "user": self.user,
            "password": self.password,
            "warehouse": self.warehouse,
            "database": self.database,
            "schema": self.schema,
            "client_session_keep_alive": True,
            "network_timeout": 60,
            "login_timeout": 30,
        }

    @property
    def minimal_connect_kwargs(self) -> dict:
        """Account login only; avoids errors when named warehouse/database/schema are not created yet."""
        return {
            "account": self.account,
            "user": self.user,
            "password": self.password,
            "client_session_keep_alive": True,
            "network_timeout": 60,
            "login_timeout": 30,
        }

    def validate(self):
        self.refresh_from_env()
        missing = [
            k
            for k in ("account", "user", "password", "warehouse", "database", "schema")
            if not getattr(self, k)
        ]
        if missing:
            raise ValueError(
                f"Missing required Snowflake env vars: {', '.join('SNOWFLAKE_' + m.upper() for m in missing)}"
            )

    def provision_account_objects(self, conn: snowflake.connector.SnowflakeConnection) -> None:
        """Create warehouse, database, and schema if missing (requires appropriate Snowflake privileges)."""
        if not auto_provision_enabled():
            return
        self.refresh_from_env()
        wh = quote_snowflake_identifier(self.warehouse)
        db = quote_snowflake_identifier(self.database)
        sch = quote_snowflake_identifier(self.schema)
        cur = conn.cursor()
        try:
            cur.execute(
                f"CREATE WAREHOUSE IF NOT EXISTS {wh} "
                "WAREHOUSE_SIZE = 'XSMALL' "
                "AUTO_SUSPEND = 60 AUTO_RESUME = TRUE INITIALLY_SUSPENDED = TRUE"
            )
            cur.execute(f"USE WAREHOUSE {wh}")
            cur.execute(f"CREATE DATABASE IF NOT EXISTS {db}")
            cur.execute(f"USE DATABASE {db}")
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {sch}")
        except ProgrammingError:
            logger.exception(
                "Snowflake auto-provision failed (need CREATE WAREHOUSE / CREATE DATABASE / CREATE SCHEMA "
                "or set SNOWFLAKE_AUTO_PROVISION=false and create objects in the UI)."
            )
            raise
        finally:
            cur.close()

    def apply_session_context(self, conn: snowflake.connector.SnowflakeConnection) -> None:
        """Set warehouse, database, schema, and tuning — required for CREATE TABLE if session has no DB."""
        self.refresh_from_env()
        self.provision_account_objects(conn)
        cur = conn.cursor()
        try:
            cur.execute(f"USE WAREHOUSE {quote_snowflake_identifier(self.warehouse)}")
            cur.execute(f"USE DATABASE {quote_snowflake_identifier(self.database)}")
            cur.execute(f"USE SCHEMA {quote_snowflake_identifier(self.schema)}")
            cur.execute("ALTER SESSION SET QUERY_TAG = 'parsehub-backend'")
            cur.execute(
                "ALTER SESSION SET STATEMENT_QUEUED_TIMEOUT_IN_SECONDS = 300"
            )
            cur.execute("ALTER SESSION SET USE_CACHED_RESULT = TRUE")
            cur.execute(
                "ALTER SESSION SET TIMESTAMP_NTZ_OUTPUT_FORMAT = 'YYYY-MM-DD HH24:MI:SS'"
            )
        finally:
            cur.close()


snowflake_config = SnowflakeConfig()


class ConnectionPool:
    """Thread-safe, bounded connection pool with health-checking."""

    def __init__(self, config: SnowflakeConfig):
        self._config = config
        self._pool: queue.Queue[snowflake.connector.SnowflakeConnection] = queue.Queue(
            maxsize=config.pool_size
        )
        self._lock = threading.Lock()
        self._created = 0

    def _create_connection(self) -> snowflake.connector.SnowflakeConnection:
        self._config.refresh_from_env()
        conn = snowflake.connector.connect(**self._config.minimal_connect_kwargs)
        self._config.apply_session_context(conn)
        return conn

    def acquire(self) -> snowflake.connector.SnowflakeConnection:
        # Try to reuse an idle connection.
        while True:
            try:
                conn = self._pool.get_nowait()
            except queue.Empty:
                break
            if self._is_alive(conn):
                return conn
            self._safe_close(conn)

        # No idle connection available — create if under limit.
        with self._lock:
            if self._created < self._config.pool_size:
                self._created += 1
                return self._create_connection()

        # Pool exhausted; block until one is returned (up to 30 s).
        try:
            conn = self._pool.get(timeout=30)
            if self._is_alive(conn):
                return conn
            self._safe_close(conn)
            return self._create_connection()
        except queue.Empty:
            raise RuntimeError("Snowflake connection pool exhausted (30 s timeout)")

    def release(self, conn: snowflake.connector.SnowflakeConnection):
        if conn is None:
            return
        if self._is_alive(conn):
            try:
                self._pool.put_nowait(conn)
            except queue.Full:
                self._safe_close(conn)
        else:
            self._safe_close(conn)

    def close_all(self):
        while True:
            try:
                conn = self._pool.get_nowait()
                self._safe_close(conn)
            except queue.Empty:
                break

    @staticmethod
    def _is_alive(conn: snowflake.connector.SnowflakeConnection) -> bool:
        try:
            conn.cursor().execute("SELECT 1")
            return True
        except Exception:
            return False

    @staticmethod
    def _safe_close(conn: snowflake.connector.SnowflakeConnection):
        try:
            conn.close()
        except Exception:
            pass


_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                snowflake_config.validate()
                _pool = ConnectionPool(snowflake_config)
    return _pool


@contextmanager
def get_connection():
    """Context manager that borrows a pooled Snowflake connection.

    Usage:
        with get_connection() as conn:
            cur = conn.cursor(snowflake.connector.DictCursor)
            cur.execute(...)
    """
    pool = _get_pool()
    conn = pool.acquire()
    try:
        yield conn
    finally:
        pool.release(conn)


def execute_with_retry(conn, sql, params=None, max_retries=3):
    """Execute a SQL statement with exponential-backoff retry on transient errors."""
    last_exc = None
    for attempt in range(max_retries):
        try:
            cur = conn.cursor(snowflake.connector.DictCursor)
            if params is not None:
                cur.execute(sql, params)
            else:
                cur.execute(sql)
            return cur
        except (OperationalError, DatabaseError, ProgrammingError) as exc:
            last_exc = exc
            err_code = getattr(exc, "errno", None)
            if err_code not in TRANSIENT_ERROR_CODES and attempt > 0:
                raise
            wait = (2**attempt) * 1.0
            logger.warning(
                "Snowflake transient error (attempt %d/%d, code=%s): %s — retrying in %.1fs",
                attempt + 1,
                max_retries,
                err_code,
                exc,
                wait,
            )
            time.sleep(wait)
    raise last_exc  # type: ignore[misc]


def close_pool():
    """Gracefully close every connection in the pool (e.g. at app shutdown)."""
    global _pool
    if _pool is not None:
        _pool.close_all()
        _pool = None

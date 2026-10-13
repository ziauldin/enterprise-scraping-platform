from __future__ import annotations

"""
SnowflakeDatabase — primary database implementation.

Key characteristics:
    * Connection pool instead of open/close per call.
    * MERGE INTO for upserts.
    * %s parameter placeholders.
    * DictCursor for dict-like row access.
    * OBJECT_CONSTRUCT for JSON subqueries.
    * Batched product_data inserts for throughput.
"""

import json
import logging
import os
import re
from calendar import monthrange
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import snowflake.connector
from snowflake.connector import DictCursor

from backend.snowflake_config import get_connection, execute_with_retry
from backend.snowflake_schema import create_all_tables

logger = logging.getLogger(__name__)

PRODUCT_INSERT_BATCH_SIZE = 5000


def _snowflake_bootstrap_ddl_enabled() -> bool:
    """When true, init_db runs CREATE TABLE IF NOT EXISTS and one-off column patches.

    Default false so production workers do not re-send DDL on every process start;
    enable temporarily for a new environment or after pulling schema changes,
    or apply DDL in Snowflake separately.
    """
    return os.getenv("SNOWFLAKE_BOOTSTRAP_DDL", "false").lower() in (
        "1",
        "true",
        "yes",
    )


class SnowflakeDatabase:
    """Snowflake-backed database implementation."""

    def __init__(self):
        self.connection = None  # compatibility — callers may check this attribute
        self.init_db()

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------

    def _get_connection(self):
        """Kept for signature compatibility — returns a pool context manager."""
        return get_connection()

    def connect(self):
        """No-op persistent connection — pool handles lifecycle."""
        return None

    def disconnect(self):
        """No-op — pool handles lifecycle."""
        pass

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def init_db(self):
        if not _snowflake_bootstrap_ddl_enabled():
            print("Skipping snowflake bootstrap DDL")
            return
        with get_connection() as conn:
            print("Creating snowflake tables")
            cur = conn.cursor()
            create_all_tables(cur)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_dict(cursor) -> dict[str, Any] | None:
        """Fetch one row as a dict from a DictCursor."""
        row = cursor.fetchone()
        return dict(row) if row else None

    @staticmethod
    def _rows_to_dicts(cursor) -> list[dict[str, Any]]:
        return [dict(r) for r in cursor.fetchall()]

    def _normalize_text(self, value: str | None) -> str:
        return " ".join((value or "").strip().lower().split())

    @staticmethod
    def _to_float_or_none(value: Any) -> float | None:
        """Parse loose numeric strings (e.g. '$1,035.00') into float."""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        raw = str(value).strip()
        if not raw:
            return None
        cleaned = re.sub(r"[^0-9.\-]", "", raw)
        if cleaned in {"", "-", ".", "-."}:
            return None
        try:
            return float(cleaned)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_int_or_none(value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        raw = str(value).strip()
        if not raw:
            return None
        cleaned = re.sub(r"[^0-9\-]", "", raw)
        if cleaned in {"", "-"}:
            return None
        try:
            return int(cleaned)
        except (TypeError, ValueError):
            return None

    def _schedule_local_time_from_utc(self, utc_iso: str, timezone_name: str | None) -> str:
        raw = str(utc_iso or "").strip()
        if not raw or not timezone_name:
            return raw
        try:
            utc_dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            local_dt = utc_dt.astimezone(ZoneInfo(str(timezone_name)))
            return local_dt.strftime("%Y-%m-%dT%H:%M")
        except Exception:
            return raw

    def _parse_local_hhmm(self, value: str | None) -> time:
        raw = str(value or "").strip()
        if not raw:
            raise ValueError("local_time is required for recurring schedules")
        try:
            parsed = datetime.strptime(raw, "%H:%M")
        except ValueError as exc:
            raise ValueError("local_time must be in HH:MM format") from exc
        return parsed.time().replace(second=0, microsecond=0)

    def _iso_utc(self, value: datetime) -> str:
        return value.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _next_recurring_run_utc(
        self,
        frequency: str,
        timezone_name: str,
        local_time_hhmm: str,
        weekday: int | None = None,
        day_of_month: int | None = None,
        now_utc_iso: str | None = None,
    ) -> tuple[str, str]:
        tz = ZoneInfo(timezone_name)
        target_time = self._parse_local_hhmm(local_time_hhmm)
        if now_utc_iso:
            now_utc = datetime.fromisoformat(str(now_utc_iso).replace("Z", "+00:00"))
        else:
            now_utc = datetime.utcnow().replace(tzinfo=ZoneInfo("UTC"))
        now_local = now_utc.astimezone(tz)
        freq = str(frequency or "").strip().lower()
        candidate: datetime | None = None

        if freq == "daily":
            candidate = now_local.replace(hour=target_time.hour, minute=target_time.minute, second=0, microsecond=0)
            if candidate <= now_local:
                candidate = candidate + timedelta(days=1)
        elif freq == "weekly":
            if weekday is None or weekday < 0 or weekday > 6:
                raise ValueError("recurrence_weekday must be between 0 and 6 for weekly schedules")
            days_ahead = (int(weekday) - now_local.weekday()) % 7
            candidate = (now_local + timedelta(days=days_ahead)).replace(
                hour=target_time.hour, minute=target_time.minute, second=0, microsecond=0
            )
            if candidate <= now_local:
                candidate = candidate + timedelta(days=7)
        elif freq == "monthly":
            if day_of_month is None or int(day_of_month) < 1 or int(day_of_month) > 31:
                raise ValueError("recurrence_day_of_month must be between 1 and 31 for monthly schedules")
            year = now_local.year
            month = now_local.month
            while True:
                dom = min(int(day_of_month), monthrange(year, month)[1])
                candidate = datetime(year, month, dom, target_time.hour, target_time.minute, tzinfo=tz)
                if candidate > now_local:
                    break
                if month == 12:
                    year += 1
                    month = 1
                else:
                    month += 1
        else:
            raise ValueError("recurrence_frequency must be one of: daily, weekly, monthly")

        assert candidate is not None
        return self._iso_utc(candidate), candidate.strftime("%Y-%m-%dT%H:%M")

    # ------------------------------------------------------------------
    # metadata table
    # ------------------------------------------------------------------

    def _match_metadata_id(self, cursor, title: str) -> str | None:
        normalized_title = self._normalize_text(title)
        website = self.extract_website_from_title(title)
        cursor.execute(
            """
            SELECT personal_project_id
            FROM metadata
            WHERE LOWER(project_name) = %s
               OR LOWER(project_name) = %s
               OR LOWER(COALESCE(website_url, '')) LIKE %s
            ORDER BY COALESCE(update_date, create_date) DESC, personal_project_id DESC
            LIMIT 1
            """,
            (title.lower(), normalized_title, f"%{website.lower()}%"),
        )
        row = cursor.fetchone()
        return row["PERSONAL_PROJECT_ID"] if row else None

    def add_metadata_record(
        self,
        personal_project_id: str,
        project_id_parsehub: str | None,
        project_name: str,
        website_type: str | None = None,
        last_run_data: str | None = None,
        create_date: str | None = None,
        update_date: str | None = None,
        region: str | None = None,
        country: str | None = None,
        brand: str | None = None,
        website_url: str | None = None,
        next_page_url: str | None = None,
        total_pages: int | None = None,
        total_products: int | None = None,
        current_page_scraped: int = 0,
        current_product_scraped: int = 0,
    ) -> str | None:
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            params = (
                personal_project_id,
                project_id_parsehub,
                project_name,
                last_run_data,
                create_date,
                update_date or datetime.utcnow().isoformat(),
                region,
                country,
                brand,
                website_url,
                next_page_url,
                total_pages,
                total_products,
                current_page_scraped,
                current_product_scraped,
            )
            cur.execute(
                """
                MERGE INTO metadata AS tgt
                USING (SELECT %s AS personal_project_id) AS src
                ON tgt.personal_project_id = src.personal_project_id
                WHEN MATCHED THEN UPDATE SET
                    project_id_parsehub = %s,
                    project_name = %s,
                    website_type = %s,
                    last_run_data = %s,
                    create_date = %s,
                    update_date = %s,
                    region = %s,
                    country = %s,
                    brand = %s,
                    website_url = %s,
                    next_page_url = %s,
                    total_pages = %s,
                    total_products = %s,
                    current_page_scraped = %s,
                    current_product_scraped = %s
                WHEN NOT MATCHED THEN INSERT (
                    personal_project_id, project_id_parsehub, project_name,
                    website_type,
                    last_run_data, create_date, update_date,
                    region, country, brand, website_url, next_page_url,
                    total_pages, total_products,
                    current_page_scraped, current_product_scraped
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    personal_project_id,  # USING key
                    # WHEN MATCHED SET values
                    project_id_parsehub, project_name, website_type, last_run_data,
                    create_date, update_date or datetime.utcnow().isoformat(),
                    region, country, brand, website_url, next_page_url,
                    total_pages, total_products,
                    current_page_scraped, current_product_scraped,
                    # WHEN NOT MATCHED INSERT values
                    personal_project_id, project_id_parsehub, project_name,
                    website_type,
                    last_run_data, create_date,
                    update_date or datetime.utcnow().isoformat(),
                    region, country, brand, website_url, next_page_url,
                    total_pages, total_products,
                    current_page_scraped, current_product_scraped,
                ),
            )
            self._sync_project_from_metadata_cursor(cur, metadata_id=personal_project_id)
            return personal_project_id

    def update_metadata_progress(
        self,
        personal_project_id: str,
        current_page_scraped: int | None = None,
        current_product_scraped: int | None = None,
        next_page_url: str | None = None,
        last_run_data: str | None = None,
        update_date: str | None = None,
        completion_percentage: float | None = None,
    ) -> bool:
        del completion_percentage
        updates = ["update_date = %s"]
        params: list[Any] = [update_date or datetime.utcnow().isoformat()]

        if current_page_scraped is not None:
            updates.append("current_page_scraped = %s")
            params.append(current_page_scraped)
        if current_product_scraped is not None:
            updates.append("current_product_scraped = %s")
            params.append(current_product_scraped)
        if next_page_url is not None:
            updates.append("next_page_url = %s")
            params.append(next_page_url)
        if last_run_data is not None:
            updates.append("last_run_data = %s")
            params.append(last_run_data)

        params.append(personal_project_id)
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(
                f"UPDATE metadata SET {', '.join(updates)} WHERE personal_project_id = %s",
                params,
            )
            affected = cur.rowcount
            if affected > 0:
                self._sync_project_from_metadata_cursor(cur, metadata_id=personal_project_id)
            return affected > 0

    def update_metadata_record(self, personal_project_id: str, updates: dict[str, Any]) -> bool:
        allowed_fields = {
            "project_id_parsehub", "project_name", "region", "country", "brand",
            "website_url", "next_page_url", "total_pages", "total_products",
            "current_page_scraped", "current_product_scraped", "update_date", "last_run_data",
            "website_type",
        }
        update_parts: list[str] = []
        params: list[Any] = []
        for field, value in updates.items():
            if field not in allowed_fields:
                continue
            update_parts.append(f"{field} = %s")
            params.append(value)
        if "update_date" not in updates:
            update_parts.append("update_date = %s")
            params.append(datetime.utcnow().isoformat())
        if not update_parts:
            return False

        params.append(personal_project_id)
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(
                f"UPDATE metadata SET {', '.join(update_parts)} WHERE personal_project_id = %s",
                params,
            )
            affected = cur.rowcount
            if affected > 0:
                self._sync_project_from_metadata_cursor(cur, metadata_id=personal_project_id)
            return affected > 0

    def delete_metadata_record(self, personal_project_id: str) -> bool:
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            # Remove direct project linkage first so project details remain consistent.
            cur.execute(
                """
                UPDATE projects
                SET metadata_personal_project_id = NULL,
                    metadata_update_date = NULL
                WHERE metadata_personal_project_id = %s
                """,
                (str(personal_project_id),),
            )
            cur.execute(
                "DELETE FROM metadata WHERE personal_project_id = %s",
                (str(personal_project_id),),
            )
            return cur.rowcount > 0

    def count_metadata_filtered(
        self,
        project_id_parsehub: str | None = None,
        region: str | list[str] | None = None,
        country: str | list[str] | None = None,
        brand: str | list[str] | None = None,
        search: str | None = None,
    ) -> int:
        query = "SELECT COUNT(*) AS total FROM metadata WHERE 1=1"
        params: list[Any] = []

        def normalize_filter_values(raw: str | list[str] | None) -> list[str]:
            if raw is None:
                return []
            values = raw if isinstance(raw, list) else [raw]
            return [str(value).strip() for value in values if str(value).strip()]

        if project_id_parsehub:
            query += " AND project_id_parsehub = %s"
            params.append(project_id_parsehub)
        region_values = normalize_filter_values(region)
        if region_values:
            placeholders = ", ".join(["%s"] * len(region_values))
            query += f" AND region IN ({placeholders})"
            params.extend(region_values)
        country_values = normalize_filter_values(country)
        if country_values:
            placeholders = ", ".join(["%s"] * len(country_values))
            query += f" AND country IN ({placeholders})"
            params.extend(country_values)
        brand_values = normalize_filter_values(brand)
        if brand_values:
            placeholders = ", ".join(["%s"] * len(brand_values))
            query += f" AND brand IN ({placeholders})"
            params.extend(brand_values)
        if search:
            like = f"%{search.strip()}%"
            query += " AND (project_name LIKE %s OR project_id_parsehub LIKE %s)"
            params.extend([like, like])

        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(query, params)
            row = cur.fetchone()
            return int(row["TOTAL"]) if row else 0

    def get_metadata_filtered(
        self,
        project_id_parsehub: str | None = None,
        region: str | list[str] | None = None,
        country: str | list[str] | None = None,
        brand: str | list[str] | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM metadata WHERE 1=1"
        params: list[Any] = []

        def normalize_filter_values(raw: str | list[str] | None) -> list[str]:
            if raw is None:
                return []
            values = raw if isinstance(raw, list) else [raw]
            return [str(value).strip() for value in values if str(value).strip()]

        if project_id_parsehub:
            query += " AND project_id_parsehub = %s"
            params.append(project_id_parsehub)
        region_values = normalize_filter_values(region)
        if region_values:
            placeholders = ", ".join(["%s"] * len(region_values))
            query += f" AND region IN ({placeholders})"
            params.extend(region_values)
        country_values = normalize_filter_values(country)
        if country_values:
            placeholders = ", ".join(["%s"] * len(country_values))
            query += f" AND country IN ({placeholders})"
            params.extend(country_values)
        brand_values = normalize_filter_values(brand)
        if brand_values:
            placeholders = ", ".join(["%s"] * len(brand_values))
            query += f" AND brand IN ({placeholders})"
            params.extend(brand_values)
        if search:
            like = f"%{search.strip()}%"
            query += " AND (project_name LIKE %s OR project_id_parsehub LIKE %s)"
            params.extend([like, like])
        query += " ORDER BY COALESCE(update_date, create_date) DESC, personal_project_id DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(query, params)
            records = self._rows_to_dicts_lower(cur)
            for record in records:
                record["id"] = record["personal_project_id"]
            return records

    def get_metadata_by_id(self, metadata_id: str) -> dict[str, Any] | None:
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute("SELECT * FROM metadata WHERE personal_project_id = %s", (str(metadata_id),))
            row = cur.fetchone()
            if not row:
                return None
            record = self._lower_keys(dict(row))
            record["id"] = record["personal_project_id"]
            return record

    def get_metadata_schema_columns(self) -> list[str]:
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(
                """
                SELECT COLUMN_NAME
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = CURRENT_SCHEMA()
                  AND TABLE_NAME = 'METADATA'
                ORDER BY ORDINAL_POSITION
                """
            )
            return [str(row["COLUMN_NAME"]).lower() for row in cur.fetchall()]

    def get_all_metadata_for_export(self) -> list[dict[str, Any]]:
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute("SELECT * FROM metadata ORDER BY personal_project_id ASC")
            return self._rows_to_dicts_lower(cur)

    def get_metadata_by_project_token(self, token: str) -> dict[str, Any] | None:
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(
                """
                SELECT *
                FROM metadata
                WHERE project_id_parsehub = %s
                ORDER BY COALESCE(update_date, create_date) DESC, personal_project_id DESC
                LIMIT 1
                """,
                (token,),
            )
            row = cur.fetchone()
            return self._lower_keys(dict(row)) if row else None

    def get_distinct_metadata_values(self, field: str) -> list[str]:
        if field not in {"region", "country", "brand"}:
            return []
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(
                f"SELECT DISTINCT {field} FROM metadata WHERE {field} IS NOT NULL AND {field} != '' ORDER BY {field}"
            )
            return [row[field.upper()] for row in cur.fetchall()]

    # ------------------------------------------------------------------
    # import_batches table
    # ------------------------------------------------------------------

    def create_import_batch(self, file_name: str, record_count: int = 0, uploaded_by: str | None = None) -> int | None:
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(
                """
                INSERT INTO import_batches (file_name, record_count, status, uploaded_by)
                VALUES (%s, %s, 'success', %s)
                """,
                (file_name, record_count, uploaded_by),
            )
            cur.execute("SELECT MAX(id) AS last_id FROM import_batches")
            row = cur.fetchone()
            return row["LAST_ID"] if row else None

    def get_import_batches(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(
                """
                SELECT id, file_name, record_count, status, uploaded_by, upload_date
                FROM import_batches
                ORDER BY upload_date DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            return self._rows_to_dicts_lower(cur)

    # ------------------------------------------------------------------
    # projects table
    # ------------------------------------------------------------------

    def add_project(self, token: str, title: str, owner_email: str | None = None, main_site: str | None = None):
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(
                """
                MERGE INTO projects AS tgt
                USING (SELECT %s AS token) AS src
                ON tgt.token = src.token
                WHEN MATCHED THEN UPDATE SET
                    title = %s,
                    owner_email = %s,
                    main_site = %s,
                    updated_at = CURRENT_TIMESTAMP()
                WHEN NOT MATCHED THEN INSERT (token, title, owner_email, main_site, updated_at)
                VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP())
                """,
                (token, title, owner_email, main_site, token, title, owner_email, main_site),
            )

    def sync_projects(self, projects_list: list[dict[str, Any]]) -> dict[str, Any]:
        staged_rows: list[tuple[str, str, Any, Any]] = []
        for project in projects_list:
            token = (project.get("token") or "").strip()
            if not token:
                continue
            title = (project.get("title") or project.get("name") or token).strip() or token
            staged_rows.append((token, title, project.get("owner_email"), project.get("main_site")))

        if not staged_rows:
            return {"success": True, "inserted": 0, "updated": 0, "total": 0, "metadata_projected": 0}

        tokens = [row[0] for row in staged_rows]
        placeholders = ", ".join(["%s"] * len(tokens))
        metadata_projected = 0

        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(
                f"SELECT token FROM projects WHERE token IN ({placeholders})",
                tokens,
            )
            existing_tokens = {str(row["TOKEN"]) for row in cur.fetchall()}
            inserted = sum(1 for token in tokens if token not in existing_tokens)
            updated = len(tokens) - inserted

            cur.execute(
                """
                CREATE OR REPLACE TEMPORARY TABLE sync_projects_stage (
                    token VARCHAR,
                    title VARCHAR,
                    owner_email VARCHAR,
                    main_site VARCHAR
                )
                """
            )
            cur.executemany(
                """
                INSERT INTO sync_projects_stage (token, title, owner_email, main_site)
                VALUES (%s, %s, %s, %s)
                """,
                staged_rows,
            )
            cur.execute(
                """
                MERGE INTO projects AS tgt
                USING sync_projects_stage AS src
                ON tgt.token = src.token
                WHEN MATCHED THEN UPDATE SET
                    title = src.title,
                    owner_email = src.owner_email,
                    main_site = src.main_site,
                    updated_at = CURRENT_TIMESTAMP()
                WHEN NOT MATCHED THEN INSERT (token, title, owner_email, main_site, updated_at)
                VALUES (src.token, src.title, src.owner_email, src.main_site, CURRENT_TIMESTAMP())
                """
            )

            # Project latest metadata values back to projects in one set-based update.
            cur.execute(
                f"""
                UPDATE projects AS p
                SET
                    title = COALESCE(NULLIF(TRIM(m.project_name), ''), p.token),
                    main_site = NULLIF(TRIM(m.website_url), ''),
                    metadata_personal_project_id = m.personal_project_id,
                    metadata_update_date = m.update_date,
                    region = m.region,
                    country = m.country,
                    brand = m.brand,
                    website_url = NULLIF(TRIM(m.website_url), ''),
                    next_page_url = m.next_page_url,
                    total_pages = m.total_pages,
                    total_products = m.total_products,
                    current_page_scraped = COALESCE(m.current_page_scraped, 0),
                    current_product_scraped = COALESCE(m.current_product_scraped, 0),
                    updated_at = CURRENT_TIMESTAMP()
                FROM (
                    SELECT
                        personal_project_id, project_id_parsehub, project_name,
                        update_date, region, country, brand, website_url, next_page_url,
                        total_pages, total_products, current_page_scraped, current_product_scraped,
                        ROW_NUMBER() OVER (
                            PARTITION BY project_id_parsehub
                            ORDER BY COALESCE(update_date, create_date) DESC, personal_project_id DESC
                        ) AS rn
                    FROM metadata
                    WHERE project_id_parsehub IN ({placeholders})
                ) AS m
                WHERE p.token = m.project_id_parsehub
                  AND m.rn = 1
                """,
                tokens,
            )
            metadata_projected = max(0, cur.rowcount or 0)

        return {
            "success": True,
            "inserted": inserted,
            "updated": updated,
            "total": len(staged_rows),
            "metadata_projected": metadata_projected,
        }

    def backfill_metadata_project_tokens(self) -> dict[str, Any]:
        linked = 0
        skipped = 0
        ambiguous = 0
        metadata_projected = 0
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(
                "SELECT personal_project_id, project_name FROM metadata "
                "WHERE project_id_parsehub IS NULL OR TRIM(project_id_parsehub) = ''"
            )
            unlinked_rows = cur.fetchall()
            for row in unlinked_rows:
                personal_id = row["PERSONAL_PROJECT_ID"]
                project_name = (row["PROJECT_NAME"] or "").strip()
                if not project_name:
                    skipped += 1
                    continue
                normalized = " ".join(project_name.lower().split())
                cur.execute(
                    """
                    SELECT token FROM projects
                    WHERE LOWER(TRIM(title)) = %s OR LOWER(TRIM(title)) = %s
                    ORDER BY id ASC
                    """,
                    (project_name.lower(), normalized),
                )
                matches = cur.fetchall()
                if not matches:
                    skipped += 1
                    continue
                if len(matches) > 1:
                    exact = [m for m in matches if m["TOKEN"] and m["TOKEN"].strip()]
                    matches = exact[:1] if exact else matches[:1]
                    ambiguous += 1
                token = matches[0]["TOKEN"]
                cur.execute(
                    "UPDATE metadata SET project_id_parsehub = %s, update_date = %s WHERE personal_project_id = %s",
                    (token, datetime.utcnow().isoformat(), personal_id),
                )
                if cur.rowcount > 0 and self._sync_project_from_metadata_cursor(cur, metadata_id=personal_id):
                    metadata_projected += 1
                linked += 1
            return {
                "success": True,
                "linked": linked,
                "skipped": skipped,
                "ambiguous_resolved": ambiguous,
                "metadata_projected": metadata_projected,
                "total_processed": len(unlinked_rows),
            }

    def sync_metadata_with_projects(
        self, projects_list: list[dict[str, Any]], force_overwrite: bool = False,
    ) -> dict[str, Any]:
        linked = 0
        skipped = 0
        preserved_manual = 0
        errors: list[str] = []
        metadata_projected = 0
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            for project in projects_list:
                token = project.get("token")
                title = (project.get("title") or project.get("name") or "").strip()
                if not token or not title:
                    skipped += 1
                    continue
                cur.execute("SELECT id FROM projects WHERE token = %s", (token,))
                if not cur.fetchone():
                    skipped += 1
                    continue
                metadata_personal_id = self._match_metadata_id(cur, title)
                if metadata_personal_id is None:
                    skipped += 1
                    continue
                cur.execute(
                    "SELECT project_id_parsehub FROM metadata WHERE personal_project_id = %s",
                    (metadata_personal_id,),
                )
                metadata_row = cur.fetchone()
                if not metadata_row:
                    skipped += 1
                    continue
                current_token = (metadata_row["PROJECT_ID_PARSEHUB"] or "").strip()
                if not (force_overwrite or current_token == ""):
                    preserved_manual += 1
                    continue
                cur.execute(
                    "UPDATE metadata SET project_id_parsehub = %s, update_date = %s WHERE personal_project_id = %s",
                    (token, datetime.utcnow().isoformat(), metadata_personal_id),
                )
                if cur.rowcount > 0 and self._sync_project_from_metadata_cursor(cur, metadata_id=metadata_personal_id):
                    metadata_projected += 1
                linked += 1
            return {
                "success": True,
                "linked": linked,
                "skipped": skipped,
                "preserved_manual": preserved_manual,
                "force_overwrite": force_overwrite,
                "errors": errors,
                "metadata_projected": metadata_projected,
            }

    @staticmethod
    def extract_website_from_title(title: str) -> str:
        if not title:
            return "unknown"
        match = re.search(r"\)\s*([^_\s]+(?:\.[^_\s]+)*?)_", title)
        if match and match[1]:
            return match[1].lower()
        match = re.search(r"([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", title)
        if match:
            return match.group(1).lower()
        return "unknown"

    def _sync_project_from_metadata_cursor(
        self, cursor, *, metadata_id: str | None = None, project_token: str | None = None,
    ) -> bool:
        if not metadata_id and not project_token:
            return False
        query = """
            SELECT
                personal_project_id, project_id_parsehub, project_name,
                update_date, region, country, brand, website_url, next_page_url,
                total_pages, total_products, current_page_scraped, current_product_scraped
            FROM metadata
            WHERE 1=1
        """
        params: list[Any] = []
        if metadata_id:
            query += " AND personal_project_id = %s"
            params.append(metadata_id)
        if project_token:
            query += " AND project_id_parsehub = %s"
            params.append(project_token)
        query += " ORDER BY COALESCE(update_date, create_date) DESC, personal_project_id DESC LIMIT 1"
        cursor.execute(query, params)
        metadata_row = cursor.fetchone()
        if not metadata_row:
            return False
        token = (metadata_row["PROJECT_ID_PARSEHUB"] or "").strip()
        if not token:
            return False
        project_name = (metadata_row["PROJECT_NAME"] or "").strip()
        website_url = (metadata_row["WEBSITE_URL"] or "").strip()
        cursor.execute(
            """
            UPDATE projects SET
                title = %s,
                main_site = %s,
                metadata_personal_project_id = %s,
                metadata_update_date = %s,
                region = %s,
                country = %s,
                brand = %s,
                website_url = %s,
                next_page_url = %s,
                total_pages = %s,
                total_products = %s,
                current_page_scraped = COALESCE(%s, 0),
                current_product_scraped = COALESCE(%s, 0),
                updated_at = CURRENT_TIMESTAMP()
            WHERE token = %s
            """,
            (
                project_name or token,
                website_url or None,
                metadata_row["PERSONAL_PROJECT_ID"],
                metadata_row["UPDATE_DATE"],
                metadata_row["REGION"],
                metadata_row["COUNTRY"],
                metadata_row["BRAND"],
                website_url or None,
                metadata_row["NEXT_PAGE_URL"],
                metadata_row["TOTAL_PAGES"],
                metadata_row["TOTAL_PRODUCTS"],
                metadata_row["CURRENT_PAGE_SCRAPED"],
                metadata_row["CURRENT_PRODUCT_SCRAPED"],
                token,
            ),
        )
        return cursor.rowcount > 0

    def sync_project_from_metadata(self, metadata_id: str | None = None, project_token: str | None = None) -> bool:
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            return self._sync_project_from_metadata_cursor(cur, metadata_id=metadata_id, project_token=project_token)

    def get_distinct_project_websites(self) -> list[str]:
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute("SELECT website_url, main_site, title FROM projects ORDER BY title")
            websites = {
                self.extract_website_from_title(
                    row["WEBSITE_URL"] or row["MAIN_SITE"] or row["TITLE"]
                )
                for row in cur.fetchall()
                if row["WEBSITE_URL"] or row["MAIN_SITE"] or row["TITLE"]
            }
            return sorted(w for w in websites if w and w != "unknown")

    def list_projects(
        self,
        page: int = 1,
        limit: int = 50,
        region: str | list[str] | None = None,
        country: str | list[str] | None = None,
        brand: str | list[str] | None = None,
        website: str | list[str] | None = None,
        filter_keyword: str | None = None,
    ) -> dict[str, Any]:
        offset = max(page - 1, 0) * limit
        filters = ["1=1"]
        params: list[Any] = []

        def normalize_filter_values(raw: str | list[str] | None) -> list[str]:
            if raw is None:
                return []
            values = raw if isinstance(raw, list) else [raw]
            return [str(value).strip() for value in values if str(value).strip()]
        if filter_keyword:
            keyword = f"%{filter_keyword.lower()}%"
            filters.append("(LOWER(p.title) LIKE %s OR LOWER(COALESCE(p.main_site, '')) LIKE %s)")
            params.extend([keyword, keyword])
        region_values = normalize_filter_values(region)
        if region_values:
            placeholders = ", ".join(["%s"] * len(region_values))
            filters.append(f"p.region IN ({placeholders})")
            params.extend(region_values)

        country_values = normalize_filter_values(country)
        if country_values:
            placeholders = ", ".join(["%s"] * len(country_values))
            filters.append(f"p.country IN ({placeholders})")
            params.extend(country_values)

        brand_values = normalize_filter_values(brand)
        if brand_values:
            placeholders = ", ".join(["%s"] * len(brand_values))
            filters.append(f"p.brand IN ({placeholders})")
            params.extend(brand_values)

        website_values = normalize_filter_values(website)
        if website_values:
            website_filters: list[str] = []
            for website_value in website_values:
                website_like = f"%{website_value.lower()}%"
                website_filters.append("(LOWER(COALESCE(p.website_url, p.main_site, '')) LIKE %s OR LOWER(p.title) LIKE %s)")
                params.extend([website_like, website_like])
            filters.append(f"({' OR '.join(website_filters)})")

        where_clause = " AND ".join(filters)
        count_query = f"SELECT COUNT(*) AS count FROM projects p WHERE {where_clause}"

        query = f"""
            WITH latest_metadata AS (
                SELECT m.*,
                       ROW_NUMBER() OVER (
                           PARTITION BY COALESCE(m.project_id_parsehub, m.personal_project_id)
                           ORDER BY COALESCE(m.update_date, m.create_date) DESC, m.personal_project_id DESC
                       ) AS rn
                FROM metadata m
            ),
            latest_runs AS (
                SELECT r.*,
                       ROW_NUMBER() OVER (
                           PARTITION BY r.project_id
                           ORDER BY COALESCE(r.updated_at, r.created_at) DESC, r.id DESC
                       ) AS rn
                FROM runs r
            )
            SELECT
                p.id, p.token, p.title, p.owner_email, p.main_site,
                p.region, p.country, p.brand, p.website_url, p.next_page_url,
                p.total_pages, p.total_products,
                p.current_page_scraped, p.current_product_scraped,
                p.metadata_personal_project_id, p.metadata_update_date,
                p.created_at, p.updated_at,
                m.personal_project_id  AS m_personal_project_id,
                m.project_id_parsehub  AS m_project_id_parsehub,
                m.project_name         AS m_project_name,
                m.last_run_data        AS m_last_run_data,
                m.create_date          AS m_create_date,
                m.update_date          AS m_update_date,
                m.region               AS m_region,
                m.country              AS m_country,
                m.brand                AS m_brand,
                m.website_url          AS m_website_url,
                m.next_page_url        AS m_next_page_url,
                m.total_pages          AS m_total_pages,
                m.total_products       AS m_total_products,
                m.current_page_scraped AS m_current_page_scraped,
                m.current_product_scraped AS m_current_product_scraped,
                lr.run_token           AS lr_run_token,
                lr.status              AS lr_status,
                lr.pages_requested     AS lr_pages_requested,
                lr.pages_scraped       AS lr_pages_scraped,
                lr.data_ready          AS lr_data_ready,
                lr.start_time          AS lr_start_time,
                lr.end_time            AS lr_end_time,
                lr.updated_at          AS lr_updated_at,
                (SELECT COUNT(*) FROM product_data pd WHERE pd.project_id = p.id) AS stored_records
            FROM projects p
            LEFT JOIN latest_metadata m
                ON m.rn = 1
                AND (
                    (p.metadata_personal_project_id IS NOT NULL
                     AND p.metadata_personal_project_id != ''
                     AND m.personal_project_id = p.metadata_personal_project_id)
                    OR
                    ((p.metadata_personal_project_id IS NULL OR p.metadata_personal_project_id = '')
                     AND m.project_id_parsehub = p.token)
                )
            LEFT JOIN latest_runs lr
                ON lr.project_id = p.id AND lr.rn = 1
            WHERE {where_clause}
            ORDER BY p.updated_at DESC, p.id DESC
            LIMIT %s OFFSET %s
        """

        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(count_query, params)
            total = cur.fetchone()["COUNT"]
            cur.execute(query, [*params, limit, offset])
            projects: list[dict[str, Any]] = []
            for row in cur.fetchall():
                metadata = None
                if row.get("M_PERSONAL_PROJECT_ID"):
                    metadata = {
                        "personal_project_id": row["M_PERSONAL_PROJECT_ID"],
                        "project_id_parsehub": row["M_PROJECT_ID_PARSEHUB"],
                        "project_name": row["M_PROJECT_NAME"],
                        "last_run_data": row["M_LAST_RUN_DATA"],
                        "create_date": row["M_CREATE_DATE"],
                        "update_date": row["M_UPDATE_DATE"],
                        "region": row["M_REGION"],
                        "country": row["M_COUNTRY"],
                        "brand": row["M_BRAND"],
                        "website_url": row["M_WEBSITE_URL"],
                        "next_page_url": row["M_NEXT_PAGE_URL"],
                        "total_pages": row["M_TOTAL_PAGES"],
                        "total_products": row["M_TOTAL_PRODUCTS"],
                        "current_page_scraped": row["M_CURRENT_PAGE_SCRAPED"],
                        "current_product_scraped": row["M_CURRENT_PRODUCT_SCRAPED"],
                    }
                last_run = None
                if row.get("LR_RUN_TOKEN"):
                    last_run = {
                        "run_token": row["LR_RUN_TOKEN"],
                        "status": row["LR_STATUS"],
                        "pages_requested": row["LR_PAGES_REQUESTED"],
                        "pages_scraped": row["LR_PAGES_SCRAPED"],
                        "data_ready": row["LR_DATA_READY"],
                        "start_time": row["LR_START_TIME"],
                        "end_time": row["LR_END_TIME"],
                        "updated_at": str(row["LR_UPDATED_AT"]) if row["LR_UPDATED_AT"] else None,
                    }
                projects.append({
                    "id": row["ID"],
                    "token": row["TOKEN"],
                    "title": row["TITLE"],
                    "owner_email": row["OWNER_EMAIL"],
                    "main_site": row["MAIN_SITE"],
                    "region": row["REGION"],
                    "country": row["COUNTRY"],
                    "brand": row["BRAND"],
                    "website_url": row["WEBSITE_URL"],
                    "next_page_url": row["NEXT_PAGE_URL"],
                    "total_pages": row["TOTAL_PAGES"],
                    "total_products": row["TOTAL_PRODUCTS"],
                    "current_page_scraped": row["CURRENT_PAGE_SCRAPED"],
                    "current_product_scraped": row["CURRENT_PRODUCT_SCRAPED"],
                    "metadata_personal_project_id": row["METADATA_PERSONAL_PROJECT_ID"],
                    "metadata_update_date": row["METADATA_UPDATE_DATE"],
                    "created_at": str(row["CREATED_AT"]) if row["CREATED_AT"] else None,
                    "updated_at": str(row["UPDATED_AT"]) if row["UPDATED_AT"] else None,
                    "website": self.extract_website_from_title(
                        row["WEBSITE_URL"] or row["MAIN_SITE"] or row["TITLE"]
                    ),
                    "metadata": metadata,
                    "last_run": last_run,
                    "stored_records": row["STORED_RECORDS"],
                })
            return {
                "success": True,
                "projects": projects,
                "pagination": {
                    "page": page,
                    "limit": limit,
                    "total": total,
                    "total_pages": (total + limit - 1) // limit if limit else 1,
                    "has_more": offset + limit < total,
                },
            }

    def get_project_by_token(self, token: str) -> dict[str, Any] | None:
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(
                """
                SELECT id, token, title, owner_email, main_site,
                       region, country, brand, website_url, next_page_url,
                       total_pages, total_products,
                       current_page_scraped, current_product_scraped,
                       metadata_personal_project_id, metadata_update_date,
                       created_at, updated_at
                FROM projects WHERE token = %s
                """,
                (token,),
            )
            row = cur.fetchone()
            if not row:
                return None
            project_id = row["ID"]
            metadata_personal_id = row["METADATA_PERSONAL_PROJECT_ID"]
            if metadata_personal_id:
                cur.execute("SELECT * FROM metadata WHERE personal_project_id = %s", (str(metadata_personal_id),))
            else:
                cur.execute(
                    """
                    SELECT *
                    FROM metadata
                    WHERE project_id_parsehub = %s
                    ORDER BY COALESCE(update_date, create_date) DESC, personal_project_id DESC
                    LIMIT 1
                    """,
                    (token,),
                )
            metadata_row = cur.fetchone()
            metadata = self._lower_keys(dict(metadata_row)) if metadata_row else None
            if metadata:
                metadata["id"] = metadata["personal_project_id"]

            cur.execute(
                """
                SELECT run_token, status, pages_requested, pages_scraped, data_ready,
                       start_time, end_time, duration_seconds, project_run_cumulative_id,
                       created_at, updated_at
                FROM runs
                WHERE project_id = %s
                ORDER BY COALESCE(updated_at, created_at) DESC, id DESC
                LIMIT 10
                """,
                (project_id,),
            )
            runs = self._rows_to_dicts_lower(cur)

            cur.execute(
                """
                SELECT
                    COUNT(*) AS total_runs,
                    SUM(CASE WHEN status = 'complete' THEN 1 ELSE 0 END) AS completed_runs,
                    SUM(CASE WHEN status IN ('running', 'queued') THEN 1 ELSE 0 END) AS active_runs,
                    SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled_runs,
                    COALESCE(SUM(pages_scraped), 0) AS total_pages_scraped,
                    MAX(start_time) AS last_run_date,
                    COALESCE(AVG(pages_scraped), 0) AS average_pages_per_run
                FROM runs
                WHERE project_id = %s
                """,
                (project_id,),
            )
            stats_row = cur.fetchone() or {}
            total_runs = stats_row.get("TOTAL_RUNS") or 0
            completed_runs = stats_row.get("COMPLETED_RUNS") or 0
            success_rate = (completed_runs / total_runs * 100) if total_runs else 0
            stats = {
                "total_runs": total_runs,
                "completed_runs": completed_runs,
                "active_runs": stats_row.get("ACTIVE_RUNS") or 0,
                "cancelled_runs": stats_row.get("CANCELLED_RUNS") or 0,
                "pages_scraped": stats_row.get("TOTAL_PAGES_SCRAPED") or 0,
                "last_run_date": stats_row.get("LAST_RUN_DATE"),
                "average_pages_per_run": round(float(stats_row.get("AVERAGE_PAGES_PER_RUN") or 0), 2),
                "success_rate": round(success_rate, 2),
            }

            cur.execute(
                """
                SELECT *
                FROM project_run_cumulative_sessions
                WHERE project_id = %s
                ORDER BY is_active DESC, started_at DESC, id DESC
                LIMIT 1
                """,
                (project_id,),
            )
            cumulative_row = cur.fetchone()
            cumulative_session = self._lower_keys(dict(cumulative_row)) if cumulative_row else None

            metadata_dict = metadata if isinstance(metadata, dict) else {}
            completion_progress = self.get_project_completion_progress(
                project_id=project_id,
                website_type=metadata_dict.get("website_type"),
                total_pages=metadata_dict.get("total_pages"),
                total_products=metadata_dict.get("total_products"),
                current_cumulative_id=(cumulative_session or {}).get("project_run_cumulative_id"),
                runs=runs,
                confirmed_pages_override=self._to_int_or_none(row["CURRENT_PAGE_SCRAPED"]),
            )

            return {
                "id": project_id,
                "token": row["TOKEN"],
                "title": row["TITLE"],
                "owner_email": row["OWNER_EMAIL"],
                "main_site": row["MAIN_SITE"],
                "region": row["REGION"],
                "country": row["COUNTRY"],
                "brand": row["BRAND"],
                "website_url": row["WEBSITE_URL"],
                "next_page_url": row["NEXT_PAGE_URL"],
                "total_pages": row["TOTAL_PAGES"],
                "total_products": row["TOTAL_PRODUCTS"],
                "current_page_scraped": row["CURRENT_PAGE_SCRAPED"],
                "current_product_scraped": row["CURRENT_PRODUCT_SCRAPED"],
                "metadata_personal_project_id": row["METADATA_PERSONAL_PROJECT_ID"],
                "metadata_update_date": row["METADATA_UPDATE_DATE"],
                "created_at": str(row["CREATED_AT"]) if row["CREATED_AT"] else None,
                "updated_at": str(row["UPDATED_AT"]) if row["UPDATED_AT"] else None,
                "metadata": metadata,
                "last_run": runs[0] if runs else None,
                "runs": runs,
                "run_stats": stats,
                "current_cumulative_session": cumulative_session,
                "completion_progress": completion_progress,
                # Avoid expensive product stats scan on project detail fetch.
                # Dedicated stats endpoint is loaded separately by the UI.
                "stored_records": int(row["CURRENT_PRODUCT_SCRAPED"] or row["TOTAL_PRODUCTS"] or 0),
            }

    def get_project_completion_progress(
        self,
        project_id: int,
        website_type: str | None,
        total_pages: int | str | None,
        total_products: int | str | None = None,
        current_cumulative_id: str | None = None,
        runs: list[dict[str, Any]] | None = None,
        confirmed_pages_override: int | None = None,
    ) -> dict[str, Any]:
        """Compute hybrid completion progress from confirmed DB + optional live run progress."""
        resolved_website_type = str(website_type).strip() if website_type else None
        resolved_total_pages = self._to_int_or_none(total_pages) or 0
        resolved_total_products = self._to_int_or_none(total_products) or 0
        active_statuses = {"initialized", "running", "queued"}
        completed_statuses = {"complete", "completed", "success", "succeeded"}

        candidate_runs = runs if runs is not None else self.get_runs_by_project(project_id, limit=50)

        # Compute a stable cumulative pages baseline from completed runs in the active session.
        # ParseHub run pages are typically reported relative to the run; summing pages_scraped
        # across completed runs in the same cumulative session gives a stable absolute total
        # that does not regress when a live run transitions to completed.
        session_completed_pages = 0
        for run in candidate_runs:
            status_value = str(run.get("status") or "").strip().lower()
            if status_value not in completed_statuses:
                continue
            if current_cumulative_id and run.get("project_run_cumulative_id") != current_cumulative_id:
                continue
            session_completed_pages += int(run.get("pages_scraped") or 0)

        # Session-scoped product_data max page. Filtering by current_cumulative_id is
        # essential — without it, a new session would inherit page numbers from the
        # previous (now-closed) session and start with non-zero confirmed_pages.
        product_data_max_page = 0
        where_sql = "project_id = %s"
        params: list[Any] = [project_id]
        if current_cumulative_id:
            where_sql += " AND project_run_cumulative_id = %s"
            params.append(current_cumulative_id)

        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(f"SELECT MAX(page_number) AS max_page FROM product_data WHERE {where_sql}", params)
            max_page_row = cur.fetchone()
            product_data_max_page = (
                int(max_page_row["MAX_PAGE"])
                if (max_page_row and max_page_row.get("MAX_PAGE") is not None)
                else 0
            )

        # The legacy override (projects.current_page_scraped) is project-wide, not
        # session-scoped, and can leak progress across sessions. Only honor it as a
        # last-resort signal when neither session-scoped source has any data — this
        # keeps fresh manual Runs starting at 0 while still surfacing ingested progress
        # if both session sources happen to be empty.
        override_value = max(0, int(confirmed_pages_override)) if confirmed_pages_override is not None else 0
        if session_completed_pages > 0 or product_data_max_page > 0:
            confirmed_pages = max(session_completed_pages, product_data_max_page)
        else:
            confirmed_pages = override_value
        # Cap confirmed pages to the project's target so cumulative over-counts (e.g. ParseHub
        # returning extra pages on the last run) cannot push displayed progress past 100%.
        if resolved_total_pages > 0:
            confirmed_pages = min(confirmed_pages, resolved_total_pages)
        active_run: dict[str, Any] | None = None
        for run in candidate_runs:
            run_status = str(run.get("status") or "").strip().lower()
            if run_status not in active_statuses:
                continue
            if current_cumulative_id and run.get("project_run_cumulative_id") != current_cumulative_id:
                continue
            active_run = run
            break

        live_pages = int((active_run or {}).get("pages_scraped") or 0)
        raw_numerator = confirmed_pages + live_pages

        if resolved_website_type == "Collective":
            formula: str | None = "collective"
            denominator = resolved_total_pages + resolved_total_products
        elif resolved_website_type == "Individual":
            formula = "individual"
            denominator = resolved_total_pages
        else:
            return {
                "website_type": resolved_website_type,
                "formula": None,
                "confirmed_pages": confirmed_pages,
                "live_pages": live_pages,
                "has_active_live_run": active_run is not None,
                "active_live_run_token": (active_run or {}).get("run_token"),
                "active_live_run_status": (active_run or {}).get("status"),
                "active_live_run_cumulative_id": (active_run or {}).get("project_run_cumulative_id"),
                "project_run_cumulative_id": current_cumulative_id,
                "numerator_pages_scraped": raw_numerator,
                "displayed_progress_pages": raw_numerator,
                "denominator": 0,
                "total_pages": resolved_total_pages,
                "total_products": resolved_total_products,
                "progress_percent": 0,
                "progress_percent_raw": 0.0,
                "status": "invalid_website_type",
                "inconsistent": False,
            }

        if denominator <= 0:
            return {
                "website_type": resolved_website_type,
                "formula": formula,
                "confirmed_pages": confirmed_pages,
                "live_pages": live_pages,
                "has_active_live_run": active_run is not None,
                "active_live_run_token": (active_run or {}).get("run_token"),
                "active_live_run_status": (active_run or {}).get("status"),
                "active_live_run_cumulative_id": (active_run or {}).get("project_run_cumulative_id"),
                "project_run_cumulative_id": current_cumulative_id,
                "numerator_pages_scraped": raw_numerator,
                "displayed_progress_pages": raw_numerator,
                "denominator": 0,
                "total_pages": resolved_total_pages,
                "total_products": resolved_total_products,
                "progress_percent": 0,
                "progress_percent_raw": 0.0,
                "status": "invalid_denominator",
                "inconsistent": False,
            }

        if raw_numerator <= 0:
            return {
                "website_type": resolved_website_type,
                "formula": formula,
                "confirmed_pages": confirmed_pages,
                "live_pages": live_pages,
                "has_active_live_run": active_run is not None,
                "active_live_run_token": (active_run or {}).get("run_token"),
                "active_live_run_status": (active_run or {}).get("status"),
                "active_live_run_cumulative_id": (active_run or {}).get("project_run_cumulative_id"),
                "project_run_cumulative_id": current_cumulative_id,
                "numerator_pages_scraped": 0,
                "displayed_progress_pages": 0,
                "denominator": denominator,
                "total_pages": resolved_total_pages,
                "total_products": resolved_total_products,
                "progress_percent": 0,
                "progress_percent_raw": 0.0,
                "status": "no_run_progress",
                "inconsistent": False,
            }

        displayed_numerator = min(raw_numerator, denominator)
        raw_percent = (raw_numerator / denominator) * 100.0
        inconsistent = raw_numerator > denominator
        clamped_percent = max(0.0, min(raw_percent, 100.0))
        progress_percent = int(round(clamped_percent))

        if inconsistent:
            status = "inconsistent_data"
        elif progress_percent >= 100:
            status = "complete"
        elif active_run is not None:
            status = "live_in_progress"
        else:
            status = "in_progress_no_active_run"

        return {
            "website_type": resolved_website_type,
            "formula": formula,
            "confirmed_pages": confirmed_pages,
            "live_pages": live_pages,
            "has_active_live_run": active_run is not None,
            "active_live_run_token": (active_run or {}).get("run_token"),
            "active_live_run_status": (active_run or {}).get("status"),
            "active_live_run_cumulative_id": (active_run or {}).get("project_run_cumulative_id"),
            "project_run_cumulative_id": current_cumulative_id,
            "numerator_pages_scraped": displayed_numerator,
            "displayed_progress_pages": displayed_numerator,
            "denominator": denominator,
            "total_pages": resolved_total_pages,
            "total_products": resolved_total_products,
            "progress_percent": progress_percent,
            "progress_percent_raw": round(raw_percent, 4),
            "status": status,
            "inconsistent": inconsistent,
        }

    def get_project_id_by_token(self, token: str) -> int | None:
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute("SELECT id FROM projects WHERE token = %s", (token,))
            row = cur.fetchone()
            return row["ID"] if row else None

    # ------------------------------------------------------------------
    # Scheduling, locks, and audit
    # ------------------------------------------------------------------

    def _recurrence_summary(
        self,
        schedule_type: str | None,
        frequency: str | None,
        weekday: int | None,
        day_of_month: int | None,
        local_time: str | None,
    ) -> str:
        schedule_kind = str(schedule_type or "one_time").strip().lower()
        if schedule_kind != "recurring":
            return "One-time run"
        freq = str(frequency or "").strip().lower()
        if freq == "daily":
            return f"Every day at {local_time or '--:--'}"
        if freq == "weekly":
            labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            idx = int(weekday) if weekday is not None else -1
            day_label = labels[idx] if 0 <= idx < len(labels) else "?"
            return f"Every {day_label} at {local_time or '--:--'}"
        if freq == "monthly":
            dom = int(day_of_month) if day_of_month is not None else "?"
            return f"Every month on day {dom} at {local_time or '--:--'}"
        return "Recurring run"

    def create_project_schedule(
        self,
        project_token: str,
        scheduled_run_time_utc: str,
        scheduled_run_time_local: str | None = None,
        timezone: str | None = None,
        schedule_type: str = "one_time",
        recurrence_frequency: str | None = None,
        recurrence_weekday: int | None = None,
        recurrence_day_of_month: int | None = None,
        local_time: str | None = None,
    ) -> dict[str, Any] | None:
        project_id = self.get_project_id_by_token(project_token)
        if project_id is None:
            return None

        now_iso = datetime.utcnow().isoformat()
        max_retries = max(0, int(os.getenv("SCHEDULED_RUN_MAX_RETRIES", "0")))
        normalized_schedule_type = str(schedule_type or "one_time").strip().lower()

        effective_utc = str(scheduled_run_time_utc)
        effective_local = scheduled_run_time_local
        recurrence_frequency_value = None
        recurrence_weekday_value = None
        recurrence_day_value = None
        local_time_value = None

        if normalized_schedule_type == "recurring":
            if not timezone:
                return None
            next_utc, next_local = self._next_recurring_run_utc(
                frequency=str(recurrence_frequency or ""),
                timezone_name=str(timezone),
                local_time_hhmm=str(local_time or ""),
                weekday=recurrence_weekday,
                day_of_month=recurrence_day_of_month,
            )
            effective_utc = next_utc
            effective_local = next_local
            recurrence_frequency_value = str(recurrence_frequency or "").strip().lower()
            recurrence_weekday_value = int(recurrence_weekday) if recurrence_weekday is not None else None
            recurrence_day_value = int(recurrence_day_of_month) if recurrence_day_of_month is not None else None
            local_time_value = str(local_time or "").strip()
        else:
            normalized_schedule_type = "one_time"

        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(
                """
                INSERT INTO scheduled_project_runs (
                    project_id, project_token, schedule_type,
                    recurrence_frequency, recurrence_weekday, recurrence_day_of_month,
                    local_time, scheduled_run_time_utc, scheduled_run_time_local, timezone,
                    is_active, status, retry_count, max_retries, next_retry_time_utc,
                    created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, 'scheduled', 0, %s, NULL, %s, %s)
                """,
                (
                    int(project_id),
                    str(project_token),
                    normalized_schedule_type,
                    recurrence_frequency_value,
                    recurrence_weekday_value,
                    recurrence_day_value,
                    local_time_value,
                    effective_utc,
                    effective_local,
                    timezone,
                    max_retries,
                    now_iso,
                    now_iso,
                ),
            )
            cur.execute(
                """
                SELECT id
                FROM scheduled_project_runs
                WHERE project_id = %s AND project_token = %s
                ORDER BY id DESC
                LIMIT 1
                """,
                (int(project_id), str(project_token)),
            )
            row = cur.fetchone()
            if not row:
                return None
            schedule_id = int(row["ID"])

            cur.execute(
                """
                INSERT INTO scheduled_run_status (
                    id, project_token, scheduled_run_time, run_token,
                    status, retry_count, max_retries, error_message, last_updated
                )
                VALUES (%s, %s, %s, NULL, 'Scheduled', 0, %s, NULL, %s)
                """,
                (schedule_id, str(project_token), str(effective_local or effective_utc), max_retries, now_iso),
            )

            cur.execute("SELECT * FROM scheduled_project_runs WHERE id = %s LIMIT 1", (schedule_id,))
            created = cur.fetchone()
            return self._lower_keys(dict(created)) if created else None

    def refresh_scheduled_run_statuses_from_runs(self) -> int:
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            now_iso = datetime.utcnow().isoformat()
            cur.execute(
                """
                SELECT s.id, COALESCE(s.schedule_type, 'one_time') AS schedule_type, r.status AS run_status
                FROM scheduled_project_runs s
                JOIN runs r ON r.run_token = s.run_token
                WHERE s.run_token IS NOT NULL
                  AND (
                    (COALESCE(s.schedule_type, 'one_time') = 'one_time' AND s.status IN ('in_progress', 'triggered', 'scheduled'))
                    OR
                    (COALESCE(s.schedule_type, 'one_time') = 'recurring' AND s.status IN ('in_progress', 'triggered'))
                  )
                """
            )
            rows = cur.fetchall()
            updated = 0
            for row in rows:
                schedule_id = int(row["ID"])
                run_status = str(row["RUN_STATUS"] or "").lower()
                schedule_type = str(row["SCHEDULE_TYPE"] or "one_time").lower()
                if schedule_type == "recurring":
                    new_status = "scheduled"
                    ui_status = "Scheduled"
                    error_message = None
                elif run_status in {"complete", "completed"}:
                    new_status = "completed"
                    ui_status = "Completed"
                    error_message = None
                elif run_status in {"cancelled", "failed", "error"}:
                    new_status = "failed"
                    ui_status = "Failed"
                    error_message = f"Run ended with status {run_status}"
                else:
                    new_status = "in_progress"
                    ui_status = "In Progress"
                    error_message = None

                cur.execute(
                    """
                    UPDATE scheduled_project_runs
                    SET status = %s,
                        completed_at = CASE WHEN %s = 'completed' THEN COALESCE(completed_at, %s) ELSE completed_at END,
                        error_message = %s,
                        updated_at = %s
                    WHERE id = %s
                    """,
                    (new_status, new_status, now_iso, error_message, now_iso, schedule_id),
                )
                cur.execute(
                    """
                    UPDATE scheduled_run_status
                    SET status = %s,
                        error_message = %s,
                        last_updated = %s
                    WHERE id = %s
                    """,
                    (ui_status, error_message, now_iso, schedule_id),
                )
                updated += 1
            return updated

    def get_scheduled_run_by_id(self, schedule_id: int) -> dict[str, Any] | None:
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(
                "SELECT * FROM scheduled_project_runs WHERE id = %s LIMIT 1",
                (int(schedule_id),),
            )
            row = cur.fetchone()
            return self._lower_keys(dict(row)) if row else None

    def claim_due_scheduled_runs(
        self,
        now_utc_iso: str,
        limit: int = 25,
        stale_triggered_before_iso: str | None = None,
    ) -> list[dict[str, Any]]:
        claimed_rows: list[dict[str, Any]] = []
        claim_time = datetime.utcnow().isoformat()
        max_limit = max(1, int(limit))
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            if stale_triggered_before_iso:
                cur.execute(
                    """
                    SELECT *
                    FROM scheduled_project_runs
                    WHERE (
                        is_active = TRUE
                        AND status = 'scheduled'
                        AND scheduled_run_time_utc <= %s
                    )
                    OR (
                        is_active = TRUE
                        AND status = 'triggered'
                        AND (run_token IS NULL OR TRIM(run_token) = '')
                        AND triggered_at IS NOT NULL
                        AND triggered_at <= %s
                        AND retry_count < CASE WHEN max_retries < 1 THEN 1 ELSE max_retries END
                        AND (schedule_type IS NULL OR schedule_type != 'recurring')
                    )
                    ORDER BY scheduled_run_time_utc ASC, id ASC
                    LIMIT %s
                    """,
                    (now_utc_iso, stale_triggered_before_iso, max_limit),
                )
            else:
                cur.execute(
                    """
                    SELECT *
                    FROM scheduled_project_runs
                    WHERE is_active = TRUE
                      AND status = 'scheduled'
                      AND scheduled_run_time_utc <= %s
                    ORDER BY scheduled_run_time_utc ASC, id ASC
                    LIMIT %s
                    """,
                    (now_utc_iso, max_limit),
                )

            for row in cur.fetchall():
                row_dict = self._lower_keys(dict(row))
                row_id = int(row_dict["id"])
                is_stale_recovery = (
                    str(row_dict.get("status", "")) == "triggered"
                    and not str(row_dict.get("run_token") or "").strip()
                )
                if is_stale_recovery:
                    cur.execute(
                        """
                        UPDATE scheduled_project_runs
                        SET status = 'triggered',
                            triggered_at = %s,
                            updated_at = %s,
                            retry_count = retry_count + 1
                        WHERE id = %s
                          AND status = 'triggered'
                          AND (run_token IS NULL OR TRIM(run_token) = '')
                        """,
                        (claim_time, claim_time, row_id),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE scheduled_project_runs
                        SET status = 'triggered',
                            triggered_at = %s,
                            updated_at = %s
                        WHERE id = %s
                          AND status IN ('scheduled', 'triggered')
                        """,
                        (claim_time, claim_time, row_id),
                    )

                if (cur.rowcount or 0) > 0:
                    claimed_rows.append(row_dict)

            if stale_triggered_before_iso:
                cur.execute(
                    """
                    UPDATE scheduled_project_runs
                    SET status = 'failed',
                        error_message = 'Run trigger timed out after max retries',
                        updated_at = %s
                    WHERE status = 'triggered'
                      AND (run_token IS NULL OR TRIM(run_token) = '')
                      AND triggered_at IS NOT NULL
                      AND triggered_at <= %s
                      AND retry_count >= CASE WHEN max_retries < 1 THEN 1 ELSE max_retries END
                    """,
                    (claim_time, stale_triggered_before_iso),
                )
                cur.execute(
                    """
                    UPDATE scheduled_run_status
                    SET status = 'Failed',
                        error_message = 'Run trigger timed out after max retries',
                        last_updated = %s
                    WHERE id IN (
                        SELECT id
                        FROM scheduled_project_runs
                        WHERE status = 'failed'
                          AND error_message = 'Run trigger timed out after max retries'
                    )
                    """,
                    (claim_time,),
                )

        return claimed_rows

    def mark_scheduled_run_failed(
        self, schedule_id: int, error_message: str, force_fail: bool = False
    ) -> bool:
        now_iso = datetime.utcnow().isoformat()
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(
                """
                SELECT retry_count, max_retries, timezone
                FROM scheduled_project_runs
                WHERE id = %s
                LIMIT 1
                """,
                (int(schedule_id),),
            )
            row = cur.fetchone()
            if not row:
                return False

            retry_count = int(row["RETRY_COUNT"] or 0)
            max_retries = int(row["MAX_RETRIES"] or 0)
            timezone_name = str(row["TIMEZONE"] or "").strip() or None
            should_retry = not force_fail and retry_count < max_retries

            if should_retry:
                retry_delay = max(15, int(os.getenv("SCHEDULED_RUN_RETRY_DELAY_SECONDS", "60")))
                next_retry_dt = datetime.utcnow().timestamp() + (retry_delay * (2 ** retry_count))
                next_retry_iso = datetime.utcfromtimestamp(next_retry_dt).strftime("%Y-%m-%dT%H:%M:%SZ")
                next_retry_local = self._schedule_local_time_from_utc(next_retry_iso, timezone_name)
                next_retry_count = retry_count + 1

                cur.execute(
                    """
                    UPDATE scheduled_project_runs
                    SET status = 'scheduled',
                        retry_count = %s,
                        scheduled_run_time_utc = %s,
                        scheduled_run_time_local = %s,
                        next_retry_time_utc = %s,
                        error_message = %s,
                        updated_at = %s
                    WHERE id = %s
                    """,
                    (
                        next_retry_count,
                        next_retry_iso,
                        next_retry_local,
                        next_retry_iso,
                        str(error_message)[:2000],
                        now_iso,
                        int(schedule_id),
                    ),
                )
                cur.execute(
                    """
                    UPDATE scheduled_run_status
                    SET status = 'Scheduled',
                        retry_count = %s,
                        max_retries = %s,
                        scheduled_run_time = %s,
                        error_message = %s,
                        last_updated = %s
                    WHERE id = %s
                    """,
                    (
                        next_retry_count,
                        max_retries,
                        next_retry_local,
                        f"{str(error_message)[:1200]} | retry {next_retry_count}/{max_retries} scheduled",
                        now_iso,
                        int(schedule_id),
                    ),
                )
                return True

            cur.execute(
                """
                UPDATE scheduled_project_runs
                SET status = 'failed',
                    error_message = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (str(error_message)[:2000], now_iso, int(schedule_id)),
            )
            cur.execute(
                """
                UPDATE scheduled_run_status
                SET status = 'Failed',
                    retry_count = %s,
                    error_message = %s,
                    last_updated = %s
                WHERE id = %s
                """,
                (retry_count, str(error_message)[:2000], now_iso, int(schedule_id)),
            )
            return (cur.rowcount or 0) > 0

    def mark_scheduled_run_in_progress(self, schedule_id: int, run_token: str | None = None) -> bool:
        now_iso = datetime.utcnow().isoformat()
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(
                """
                UPDATE scheduled_project_runs
                SET status = 'in_progress',
                    run_token = COALESCE(%s, run_token),
                    next_retry_time_utc = NULL,
                    triggered_at = COALESCE(triggered_at, %s),
                    updated_at = %s
                WHERE id = %s
                """,
                (run_token, now_iso, now_iso, int(schedule_id)),
            )
            cur.execute(
                """
                UPDATE scheduled_run_status
                SET run_token = COALESCE(%s, run_token),
                    status = 'In Progress',
                    error_message = NULL,
                    last_updated = %s
                WHERE id = %s
                """,
                (run_token, now_iso, int(schedule_id)),
            )
            return (cur.rowcount or 0) > 0

    def mark_recurring_run_triggered(
        self, schedule_id: int, run_token: str | None = None
    ) -> bool:
        now_iso = datetime.utcnow().isoformat()
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(
                """
                SELECT recurrence_frequency, recurrence_weekday, recurrence_day_of_month,
                       local_time, timezone, scheduled_run_time_utc
                FROM scheduled_project_runs
                WHERE id = %s AND schedule_type = 'recurring' AND is_active = TRUE
                LIMIT 1
                """,
                (int(schedule_id),),
            )
            row = cur.fetchone()
            if not row:
                return False

            current_occurrence_utc = str(row["SCHEDULED_RUN_TIME_UTC"])
            next_utc, next_local = self._next_recurring_run_utc(
                frequency=str(row["RECURRENCE_FREQUENCY"] or ""),
                timezone_name=str(row["TIMEZONE"] or ""),
                local_time_hhmm=str(row["LOCAL_TIME"] or ""),
                weekday=(int(row["RECURRENCE_WEEKDAY"]) if row["RECURRENCE_WEEKDAY"] is not None else None),
                day_of_month=(int(row["RECURRENCE_DAY_OF_MONTH"]) if row["RECURRENCE_DAY_OF_MONTH"] is not None else None),
                now_utc_iso=current_occurrence_utc,
            )

            cur.execute(
                """
                UPDATE scheduled_project_runs
                SET status = 'scheduled',
                    run_token = COALESCE(%s, run_token),
                    last_claimed_occurrence_utc = %s,
                    scheduled_run_time_utc = %s,
                    scheduled_run_time_local = %s,
                    next_retry_time_utc = NULL,
                    triggered_at = %s,
                    updated_at = %s
                WHERE id = %s AND schedule_type = 'recurring'
                """,
                (run_token, current_occurrence_utc, next_utc, next_local, now_iso, now_iso, int(schedule_id)),
            )
            cur.execute(
                """
                UPDATE scheduled_run_status
                SET run_token = COALESCE(%s, run_token),
                    status = 'Scheduled',
                    scheduled_run_time = %s,
                    error_message = NULL,
                    last_updated = %s
                WHERE id = %s
                """,
                (run_token, next_local, now_iso, int(schedule_id)),
            )
            return (cur.rowcount or 0) > 0

    def mark_recurring_run_skipped(self, schedule_id: int, error_message: str) -> bool:
        now_iso = datetime.utcnow().isoformat()
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(
                """
                SELECT recurrence_frequency, recurrence_weekday, recurrence_day_of_month,
                       local_time, timezone, scheduled_run_time_utc
                FROM scheduled_project_runs
                WHERE id = %s AND schedule_type = 'recurring' AND is_active = TRUE
                LIMIT 1
                """,
                (int(schedule_id),),
            )
            row = cur.fetchone()
            if not row:
                return False

            current_occurrence_utc = str(row["SCHEDULED_RUN_TIME_UTC"])
            next_utc, next_local = self._next_recurring_run_utc(
                frequency=str(row["RECURRENCE_FREQUENCY"] or ""),
                timezone_name=str(row["TIMEZONE"] or ""),
                local_time_hhmm=str(row["LOCAL_TIME"] or ""),
                weekday=(int(row["RECURRENCE_WEEKDAY"]) if row["RECURRENCE_WEEKDAY"] is not None else None),
                day_of_month=(int(row["RECURRENCE_DAY_OF_MONTH"]) if row["RECURRENCE_DAY_OF_MONTH"] is not None else None),
                now_utc_iso=current_occurrence_utc,
            )

            cur.execute(
                """
                UPDATE scheduled_project_runs
                SET status = 'scheduled',
                    last_claimed_occurrence_utc = %s,
                    scheduled_run_time_utc = %s,
                    scheduled_run_time_local = %s,
                    next_retry_time_utc = NULL,
                    error_message = %s,
                    updated_at = %s
                WHERE id = %s AND schedule_type = 'recurring'
                """,
                (current_occurrence_utc, next_utc, next_local, str(error_message)[:2000], now_iso, int(schedule_id)),
            )
            cur.execute(
                """
                UPDATE scheduled_run_status
                SET status = 'Scheduled',
                    scheduled_run_time = %s,
                    error_message = %s,
                    last_updated = %s
                WHERE id = %s
                """,
                (next_local, str(error_message)[:2000], now_iso, int(schedule_id)),
            )
            return (cur.rowcount or 0) > 0

    def get_scheduled_runs(
        self,
        project_token: str | None = None,
        limit: int = 200,
        status: str | None = None,
        schedule_type: str | None = None,
    ) -> list[dict[str, Any]]:
        params: list[Any] = []
        query = """
            SELECT
                s.id, s.project_token, p.title AS project_name, s.scheduled_run_time,
                spr.schedule_type, spr.recurrence_frequency, spr.recurrence_weekday,
                spr.recurrence_day_of_month, spr.local_time, spr.scheduled_run_time_local,
                spr.scheduled_run_time_utc, spr.timezone, spr.is_active,
                s.run_token, s.status, s.error_message, s.last_updated
            FROM scheduled_run_status s
            LEFT JOIN scheduled_project_runs spr ON spr.id = s.id
            LEFT JOIN projects p ON p.token = s.project_token
            WHERE 1=1
        """
        if project_token:
            query += " AND s.project_token = %s"
            params.append(str(project_token))
        if status:
            query += " AND LOWER(s.status) = LOWER(%s)"
            params.append(str(status))
        else:
            query += " AND s.status IN ('scheduled', 'triggered')"
        if schedule_type:
            query += " AND LOWER(COALESCE(spr.schedule_type, 'one_time')) = LOWER(%s)"
            params.append(str(schedule_type))
        query += " ORDER BY s.scheduled_run_time DESC, s.id DESC LIMIT %s"
        params.append(max(1, int(limit)))

        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(query, params)
            rows = self._rows_to_dicts_lower(cur)
            for row in rows:
                row["rule_summary"] = self._recurrence_summary(
                    schedule_type=row.get("schedule_type"),
                    frequency=row.get("recurrence_frequency"),
                    weekday=row.get("recurrence_weekday"),
                    day_of_month=row.get("recurrence_day_of_month"),
                    local_time=row.get("local_time"),
                )
            return rows

    def delete_scheduled_run(self, schedule_id: int) -> bool:
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute("DELETE FROM scheduled_project_runs WHERE id = %s", (int(schedule_id),))
            deleted = cur.rowcount > 0
            cur.execute("DELETE FROM scheduled_run_status WHERE id = %s", (int(schedule_id),))
            return deleted

    def get_run_ingestion_status(self, run_token: str) -> dict[str, Any] | None:
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute("SELECT * FROM run_ingestions WHERE run_token = %s LIMIT 1", (run_token,))
            row = cur.fetchone()
            return self._lower_keys(dict(row)) if row else None

    def get_latest_run_ingestion_by_project(self, project_id: int) -> dict[str, Any] | None:
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(
                """
                SELECT *
                FROM run_ingestions
                WHERE project_id = %s
                ORDER BY COALESCE(updated_at, created_at) DESC
                LIMIT 1
                """,
                (project_id,),
            )
            row = cur.fetchone()
            return self._lower_keys(dict(row)) if row else None

    def mark_run_ingestion(
        self,
        run_token: str,
        project_id: int,
        status: str,
        inserted_count: int = 0,
        last_error: str | None = None,
    ) -> None:
        now_iso = datetime.utcnow().isoformat()
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(
                """
                MERGE INTO run_ingestions AS tgt
                USING (SELECT %s AS run_token) AS src
                ON tgt.run_token = src.run_token
                WHEN MATCHED THEN UPDATE SET
                    status = %s,
                    inserted_count = %s,
                    last_error = %s,
                    updated_at = %s
                WHEN NOT MATCHED THEN INSERT (
                    run_token, project_id, status, inserted_count, last_error, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    run_token,
                    status,
                    max(0, int(inserted_count or 0)),
                    last_error,
                    now_iso,
                    run_token,
                    int(project_id),
                    status,
                    max(0, int(inserted_count or 0)),
                    last_error,
                    now_iso,
                    now_iso,
                ),
            )

    def acquire_automation_lock(self, lock_key: str, owner: str, ttl_seconds: int = 120) -> bool:
        now = datetime.utcnow()
        expires_iso = datetime.utcfromtimestamp(now.timestamp() + max(1, int(ttl_seconds))).isoformat()
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(
                """
                SELECT owner, expires_at
                FROM automation_locks
                WHERE lock_key = %s
                LIMIT 1
                """,
                (lock_key,),
            )
            row = cur.fetchone()
            if not row:
                cur.execute(
                    """
                    INSERT INTO automation_locks (lock_key, owner, expires_at, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (lock_key, owner, expires_iso, now.isoformat(), now.isoformat()),
                )
                return True

            expiry_dt = datetime.fromisoformat(str(row["EXPIRES_AT"])) if row.get("EXPIRES_AT") else now
            if expiry_dt <= now or row.get("OWNER") == owner:
                cur.execute(
                    """
                    UPDATE automation_locks
                    SET owner = %s, expires_at = %s, updated_at = %s
                    WHERE lock_key = %s
                    """,
                    (owner, expires_iso, now.isoformat(), lock_key),
                )
                return True
            return False

    def release_automation_lock(self, lock_key: str, owner: str | None = None) -> None:
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            if owner:
                cur.execute("DELETE FROM automation_locks WHERE lock_key = %s AND owner = %s", (lock_key, owner))
            else:
                cur.execute("DELETE FROM automation_locks WHERE lock_key = %s", (lock_key,))

    def add_automation_audit_event(
        self,
        event_type: str,
        project_id: int | None = None,
        project_token: str | None = None,
        run_token: str | None = None,
        project_run_cumulative_id: str | None = None,
        status: str | None = None,
        message: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(
                """
                INSERT INTO automation_audit_events (
                    event_type, project_id, project_token, run_token,
                    project_run_cumulative_id, status, message, details_json, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    event_type,
                    project_id,
                    project_token,
                    run_token,
                    project_run_cumulative_id,
                    status,
                    message,
                    json.dumps(details, ensure_ascii=False) if details else None,
                    datetime.utcnow().isoformat(),
                ),
            )

    def automation_audit_event_exists(
        self,
        event_type: str,
        run_token: str | None = None,
        status: str | None = None,
    ) -> bool:
        where_parts = ["event_type = %s"]
        params: list[Any] = [event_type]
        if run_token is not None:
            where_parts.append("run_token = %s")
            params.append(run_token)
        if status is not None:
            where_parts.append("status = %s")
            params.append(status)
        where_sql = " AND ".join(where_parts)
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(f"SELECT 1 FROM automation_audit_events WHERE {where_sql} LIMIT 1", params)
            return cur.fetchone() is not None

    def get_active_runs_for_reconciliation(self, limit: int = 100) -> list[dict[str, Any]]:
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(
                """
                SELECT
                    r.run_token,
                    r.project_id,
                    p.token AS project_token,
                    r.status,
                    r.pages_requested,
                    r.pages_scraped,
                    r.data_ready,
                    r.start_time,
                    r.end_time,
                    r.project_run_cumulative_id,
                    r.updated_at
                FROM runs r
                JOIN projects p ON p.id = r.project_id
                LEFT JOIN run_ingestions ri ON ri.run_token = r.run_token
                WHERE
                    (
                        LOWER(COALESCE(r.status, '')) IN ('initialized', 'running', 'queued')
                    )
                    OR
                    (
                        LOWER(COALESCE(r.status, '')) IN ('complete', 'completed', 'success', 'succeeded')
                        AND COALESCE(r.data_ready, FALSE) = TRUE
                        AND COALESCE(LOWER(ri.status), '') <> 'success'
                    )
                ORDER BY COALESCE(r.updated_at, r.created_at) ASC, r.id ASC
                LIMIT %s
                """,
                (max(1, int(limit)),),
            )
            return self._rows_to_dicts_lower(cur)

    def set_auto_resume_checkpoint(self, project_id: int, max_page_before: int) -> None:
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(
                """
                UPDATE projects
                SET auto_resume_max_page_checkpoint = %s,
                    auto_resume_blocked = FALSE,
                    updated_at = CURRENT_TIMESTAMP()
                WHERE id = %s
                """,
                (int(max_page_before), int(project_id)),
            )

    def set_auto_resume_blocked(self, project_id: int) -> None:
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(
                """
                UPDATE projects
                SET auto_resume_blocked = TRUE,
                    updated_at = CURRENT_TIMESTAMP()
                WHERE id = %s
                """,
                (int(project_id),),
            )

    def clear_auto_resume_blocked(self, project_id: int) -> None:
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(
                """
                UPDATE projects
                SET auto_resume_blocked = FALSE,
                    updated_at = CURRENT_TIMESTAMP()
                WHERE id = %s
                """,
                (int(project_id),),
            )

    def reset_project_progress_for_new_session(self, project_id: int) -> None:
        """Clear stale per-session progress markers when a fresh manual Run starts.

        A fresh Run rotates the cumulative session, so any project- or metadata-level
        page counters carried over from the previous session must be zeroed; otherwise
        the new session inherits stale values that cause:
          - Resume status to mis-report the project as already complete.
          - Completion progress to over-count (e.g., 22/21 during the run, then 21/21).
          - Auto-resume to skip resuming the new session.
        """
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(
                """
                UPDATE projects
                SET current_page_scraped = 0,
                    current_product_scraped = 0,
                    auto_resume_blocked = FALSE,
                    auto_resume_max_page_checkpoint = NULL,
                    updated_at = CURRENT_TIMESTAMP()
                WHERE id = %s
                """,
                (int(project_id),),
            )
            cur.execute(
                """
                UPDATE metadata
                SET current_page_scraped = 0,
                    current_product_scraped = 0,
                    next_page_url = website_url,
                    update_date = %s
                WHERE personal_project_id = (
                    SELECT metadata_personal_project_id
                    FROM projects
                    WHERE id = %s
                )
                """,
                (datetime.utcnow().isoformat(), int(project_id)),
            )

    def get_auto_resume_state(self, project_id: int) -> dict[str, Any]:
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(
                """
                SELECT auto_resume_blocked, auto_resume_max_page_checkpoint
                FROM projects
                WHERE id = %s
                LIMIT 1
                """,
                (int(project_id),),
            )
            row = cur.fetchone()
            if not row:
                return {"auto_resume_blocked": False, "auto_resume_max_page_checkpoint": None}
            blocked = bool(row["AUTO_RESUME_BLOCKED"]) if row["AUTO_RESUME_BLOCKED"] is not None else False
            checkpoint = (
                int(row["AUTO_RESUME_MAX_PAGE_CHECKPOINT"])
                if row["AUTO_RESUME_MAX_PAGE_CHECKPOINT"] is not None
                else None
            )
            return {
                "auto_resume_blocked": blocked,
                "auto_resume_max_page_checkpoint": checkpoint,
            }

    # ------------------------------------------------------------------
    # runs table
    # ------------------------------------------------------------------

    def upsert_run(
        self,
        project_id: int,
        run_token: str,
        status: str,
        pages_requested: int = 1,
        pages_scraped: int = 0,
        data_ready: bool = False,
        start_time: str | None = None,
        end_time: str | None = None,
        project_run_cumulative_id: str | None = None,
    ) -> int | None:
        duration_seconds = None
        if start_time and end_time:
            try:
                duration_seconds = int(
                    (
                        datetime.fromisoformat(end_time.replace("Z", "+00:00"))
                        - datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                    ).total_seconds()
                )
            except ValueError:
                duration_seconds = None

        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(
                """
                MERGE INTO runs AS tgt
                USING (SELECT %s AS run_token) AS src
                ON tgt.run_token = src.run_token
                WHEN MATCHED THEN UPDATE SET
                    status = %s,
                    pages_requested = %s,
                    pages_scraped = %s,
                    data_ready = %s,
                    start_time = COALESCE(%s, tgt.start_time),
                    end_time = COALESCE(%s, tgt.end_time),
                    project_run_cumulative_id = COALESCE(%s, tgt.project_run_cumulative_id),
                    duration_seconds = COALESCE(%s, tgt.duration_seconds),
                    updated_at = CURRENT_TIMESTAMP()
                WHEN NOT MATCHED THEN INSERT (
                    project_id, run_token, status, pages_requested, pages_scraped,
                    data_ready, start_time, end_time, project_run_cumulative_id,
                    duration_seconds, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP())
                """,
                (
                    run_token,
                    # WHEN MATCHED
                    status, pages_requested, pages_scraped, data_ready,
                    start_time, end_time, project_run_cumulative_id, duration_seconds,
                    # WHEN NOT MATCHED
                    project_id, run_token, status, pages_requested, pages_scraped,
                    data_ready, start_time, end_time, project_run_cumulative_id, duration_seconds,
                ),
            )
            cur.execute("SELECT id FROM runs WHERE run_token = %s", (run_token,))
            row = cur.fetchone()
            return row["ID"] if row else None

    def add_run(
        self,
        project_token: str,
        run_token: str,
        status: str,
        pages: int,
        start_time: str,
        end_time: str | None = None,
        data_file: str | None = None,
        is_empty: bool = False,
    ) -> int | None:
        del data_file, is_empty
        project_id = self.get_project_id_by_token(project_token)
        if project_id is None:
            return None
        return self.upsert_run(
            project_id, run_token, status, pages_requested=pages,
            pages_scraped=pages, start_time=start_time, end_time=end_time,
        )

    def update_run_status(
        self,
        run_token: str,
        status: str,
        pages_scraped: int | None = None,
        data_ready: bool | None = None,
        end_time: str | None = None,
    ) -> bool:
        updates = ["status = %s", "updated_at = CURRENT_TIMESTAMP()"]
        params: list[Any] = [status]
        if pages_scraped is not None:
            updates.append("pages_scraped = %s")
            params.append(pages_scraped)
        if data_ready is not None:
            updates.append("data_ready = %s")
            params.append(data_ready)
        if end_time is not None:
            updates.append("end_time = %s")
            params.append(end_time)
        params.append(run_token)
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(f"UPDATE runs SET {', '.join(updates)} WHERE run_token = %s", params)
            return cur.rowcount > 0

    def get_run_by_token(self, run_token: str) -> dict[str, Any] | None:
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(
                """
                SELECT r.*, p.token AS project_token, p.title AS project_title
                FROM runs r
                JOIN projects p ON p.id = r.project_id
                WHERE r.run_token = %s
                LIMIT 1
                """,
                (run_token,),
            )
            row = cur.fetchone()
            return self._lower_keys(dict(row)) if row else None

    def get_runs_by_project(self, project_id: int, limit: int = 10) -> list[dict[str, Any]]:
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(
                """
                SELECT run_token, status, pages_requested, pages_scraped, data_ready,
                       start_time, end_time, duration_seconds, project_run_cumulative_id,
                       created_at, updated_at
                FROM runs
                WHERE project_id = %s
                ORDER BY COALESCE(updated_at, created_at) DESC, id DESC
                LIMIT %s
                """,
                (project_id, limit),
            )
            return self._rows_to_dicts_lower(cur)

    def get_project_run_stats(self, project_id: int) -> dict[str, Any]:
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total_runs,
                    SUM(CASE WHEN status = 'complete' THEN 1 ELSE 0 END) AS completed_runs,
                    SUM(CASE WHEN status IN ('running', 'queued') THEN 1 ELSE 0 END) AS active_runs,
                    SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled_runs,
                    COALESCE(SUM(pages_scraped), 0) AS total_pages_scraped,
                    MAX(start_time) AS last_run_date,
                    COALESCE(AVG(pages_scraped), 0) AS average_pages_per_run
                FROM runs
                WHERE project_id = %s
                """,
                (project_id,),
            )
            row = cur.fetchone()
            total_runs = row["TOTAL_RUNS"] or 0
            completed_runs = row["COMPLETED_RUNS"] or 0
            success_rate = (completed_runs / total_runs * 100) if total_runs else 0
            return {
                "total_runs": total_runs,
                "completed_runs": completed_runs,
                "active_runs": row["ACTIVE_RUNS"] or 0,
                "cancelled_runs": row["CANCELLED_RUNS"] or 0,
                "pages_scraped": row["TOTAL_PAGES_SCRAPED"] or 0,
                "last_run_date": row["LAST_RUN_DATE"],
                "average_pages_per_run": round(float(row["AVERAGE_PAGES_PER_RUN"] or 0), 2),
                "success_rate": round(success_rate, 2),
            }

    # ------------------------------------------------------------------
    # product_data table
    # ------------------------------------------------------------------

    def insert_product_data(
        self,
        project_id: int,
        run_id: int | None = None,
        run_token: str | None = None,
        project_run_cumulative_id: str | None = None,
        product_data_list: list[dict[str, Any]] | None = None,
        columns_map: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if not product_data_list:
            return {"success": False, "error": "No product data provided", "inserted": 0}

        mapping = {
            "name": "name", "product_name": "name", "title": "name",
            "part_number": "part_number", "partnumber": "part_number", "sku": "part_number",
            "brand": "brand",
            "list_price": "list_price", "sale_price": "sale_price", "price": "sale_price",
            "case_unit_price": "case_unit_price",
            "country": "country", "currency": "currency",
            "product_url": "product_url", "url": "product_url", "link": "product_url",
            "page_number": "page_number", "page": "page_number",
            "extraction_date": "extraction_date", "date": "extraction_date",
        }
        if columns_map:
            mapping.update(columns_map)

        inserted = 0
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            batch: list[tuple] = []

            for product in product_data_list:
                if not isinstance(product, dict):
                    continue
                normalized: dict[str, Any] = {}
                for key, value in product.items():
                    mapped_key = mapping.get(key.lower())
                    if mapped_key:
                        normalized[mapped_key] = value

                batch.append((
                    project_id,
                    run_id,
                    run_token,
                    project_run_cumulative_id,
                    normalized.get("name"),
                    normalized.get("part_number"),
                    normalized.get("brand"),
                    self._to_float_or_none(normalized.get("list_price")),
                    self._to_float_or_none(normalized.get("sale_price")),
                    self._to_float_or_none(normalized.get("case_unit_price")),
                    normalized.get("country"),
                    normalized.get("currency"),
                    normalized.get("product_url"),
                    self._to_int_or_none(normalized.get("page_number")),
                    normalized.get("extraction_date") or datetime.utcnow().isoformat(),
                    "parsehub",
                    json.dumps(product, ensure_ascii=False),
                ))

                if len(batch) >= PRODUCT_INSERT_BATCH_SIZE:
                    inserted += self._flush_product_batch(cur, batch)
                    batch = []

            if batch:
                inserted += self._flush_product_batch(cur, batch)

        return {
            "success": True,
            "inserted": inserted,
            "total": len(product_data_list),
            "skipped": len(product_data_list) - inserted,
        }

    @staticmethod
    def _flush_product_batch(cursor, batch: list[tuple]) -> int:
        """Bulk-upsert a batch of product rows using MERGE INTO with a multi-row VALUES source."""
        if not batch:
            return 0
        cols = (
            "project_id", "run_id", "run_token", "project_run_cumulative_id",
            "name", "part_number", "brand", "list_price", "sale_price",
            "case_unit_price", "country", "currency", "product_url",
            "page_number", "extraction_date", "data_source", "raw_json",
        )
        placeholder_row = f"({', '.join(['%s'] * len(cols))})"
        placeholders = ", ".join([placeholder_row] * len(batch))
        flat_params = [val for row in batch for val in row]

        col_list = ", ".join(cols)
        src_col_list = ", ".join(f"src.{c}" for c in cols)
        update_set = ", ".join(
            f"tgt.{c} = src.{c}" for c in cols if c not in ("project_id", "product_url", "page_number", "run_token")
        )

        sql = f"""
            MERGE INTO product_data AS tgt
            USING (
                SELECT * FROM (
                    VALUES {placeholders}
                ) AS v({col_list})
            ) AS src
            ON tgt.project_id = src.project_id
               AND tgt.run_token = src.run_token
               AND tgt.product_url = src.product_url
               AND tgt.page_number = src.page_number
            WHEN MATCHED THEN UPDATE SET
                {update_set},
                tgt.updated_at = CURRENT_TIMESTAMP()
            WHEN NOT MATCHED THEN INSERT ({col_list}, updated_at)
            VALUES ({src_col_list}, CURRENT_TIMESTAMP())
        """
        cursor.execute(sql, flat_params)
        return cursor.rowcount

    def get_product_data_by_project(
        self,
        project_id: int,
        limit: int = 1000,
        offset: int = 0,
        cumulative_id: str | None = None,
        latest_cumulative_only: bool = True,
    ) -> list[dict[str, Any]]:
        resolved_cumulative_id = cumulative_id
        if latest_cumulative_only and not resolved_cumulative_id:
            latest_session = self.get_latest_preferred_cumulative_session(project_id)
            if latest_session:
                resolved_cumulative_id = latest_session.get("project_run_cumulative_id")

        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            if resolved_cumulative_id:
                cur.execute(
                    """
                    SELECT * FROM product_data
                    WHERE project_id = %s AND project_run_cumulative_id = %s
                    ORDER BY COALESCE(TRY_TO_TIMESTAMP_NTZ(extraction_date::STRING), created_at) DESC, id DESC
                    LIMIT %s OFFSET %s
                    """,
                    (project_id, resolved_cumulative_id, limit, offset),
                )
            else:
                cur.execute(
                    """
                    SELECT * FROM product_data
                    WHERE project_id = %s
                    ORDER BY COALESCE(TRY_TO_TIMESTAMP_NTZ(extraction_date::STRING), created_at) DESC, id DESC
                    LIMIT %s OFFSET %s
                    """,
                    (project_id, limit, offset),
                )
            return self._rows_to_dicts_lower(cur)

    def get_product_data_by_run(self, run_token: str, limit: int = 1000) -> list[dict[str, Any]]:
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(
                """
                SELECT * FROM product_data
                WHERE run_token = %s
                ORDER BY page_number ASC, id ASC
                LIMIT %s
                """,
                (run_token, limit),
            )
            return self._rows_to_dicts_lower(cur)

    def get_product_data_stats(
        self,
        project_id: int,
        cumulative_id: str | None = None,
        latest_cumulative_only: bool = True,
    ) -> dict[str, Any]:
        resolved_cumulative_id = cumulative_id
        if latest_cumulative_only and not resolved_cumulative_id:
            latest_session = self.get_latest_preferred_cumulative_session(project_id)
            if latest_session:
                resolved_cumulative_id = latest_session.get("project_run_cumulative_id")

        where_sql = "project_id = %s"
        params: list[Any] = [project_id]
        if resolved_cumulative_id:
            where_sql += " AND project_run_cumulative_id = %s"
            params.append(resolved_cumulative_id)

        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(f"SELECT COUNT(*) AS count FROM product_data WHERE {where_sql}", params)
            total_products = cur.fetchone()["COUNT"]
            cur.execute(f"SELECT COUNT(DISTINCT run_token) AS count FROM product_data WHERE {where_sql}", params)
            total_runs = cur.fetchone()["COUNT"]
            cur.execute(f"SELECT MAX(extraction_date) AS latest FROM product_data WHERE {where_sql}", params)
            latest_extraction = cur.fetchone()["LATEST"]
            cur.execute(f"SELECT MAX(page_number) AS max_page FROM product_data WHERE {where_sql}", params)
            max_page_scraped = cur.fetchone()["MAX_PAGE"]

            cur.execute(
                f"""
                SELECT country, COUNT(*) AS count
                FROM product_data
                WHERE {where_sql} AND country IS NOT NULL AND country != ''
                GROUP BY country ORDER BY count DESC LIMIT 10
                """,
                params,
            )
            top_countries = self._rows_to_dicts_lower(cur)

            cur.execute(
                f"""
                SELECT brand, COUNT(*) AS count
                FROM product_data
                WHERE {where_sql} AND brand IS NOT NULL AND brand != ''
                GROUP BY brand ORDER BY count DESC LIMIT 10
                """,
                params,
            )
            top_brands = self._rows_to_dicts_lower(cur)

            return {
                "total_products": total_products,
                "total_runs_with_data": total_runs,
                "latest_extraction": latest_extraction,
                "max_page_scraped": int(max_page_scraped) if max_page_scraped is not None else 0,
                "top_countries": top_countries,
                "top_brands": top_brands,
                "project_run_cumulative_id": resolved_cumulative_id,
            }

    def get_cumulative_grouped_stats(self, project_id: int) -> list[dict[str, Any]]:
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(
                """
                SELECT
                    COALESCE(pd.project_run_cumulative_id, 'unassigned') AS project_run_cumulative_id,
                    COALESCE(cs.status, CASE WHEN COALESCE(cs.is_active, FALSE) THEN 'active' ELSE 'unknown' END) AS status,
                    COALESCE(cs.is_active, FALSE) AS is_active,
                    COUNT(*) AS total_stored_records,
                    COUNT(DISTINCT CASE WHEN pd.page_number IS NOT NULL THEN pd.page_number END) AS distinct_page_count,
                    MAX(pd.page_number) AS max_page_number,
                    MIN(pd.extraction_date) AS first_extraction_date,
                    MAX(pd.extraction_date) AS last_extraction_date,
                    COALESCE(cs.total_runs_in_session, COUNT(DISTINCT pd.run_token)) AS total_runs_in_session,
                    MAX(COALESCE(cs.started_at, pd.created_at)) AS sort_ts
                FROM product_data pd
                LEFT JOIN project_run_cumulative_sessions cs
                    ON cs.project_id = pd.project_id
                    AND cs.project_run_cumulative_id = pd.project_run_cumulative_id
                WHERE pd.project_id = %s
                GROUP BY
                    pd.project_run_cumulative_id,
                    cs.status,
                    cs.is_active,
                    cs.total_runs_in_session
                ORDER BY is_active DESC, sort_ts DESC
                """,
                (project_id,),
            )
            rows = self._rows_to_dicts_lower(cur)
            for row in rows:
                row.pop("sort_ts", None)
            return rows

    def export_product_data_csv(self, project_id: int, output_path: str | None = None) -> str | None:
        import csv
        from pathlib import Path as _Path
        records = self.get_product_data_by_project(project_id, limit=500000, offset=0)
        if not records:
            return None
        output = _Path(output_path) if output_path else _Path(f"product_export_project_{project_id}.csv")
        columns = sorted({col for rec in records for col in rec.keys()})
        with output.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(records)
        return str(output)

    # ------------------------------------------------------------------
    # Cumulative run sessions
    # ------------------------------------------------------------------

    def _build_cumulative_id(self, project_token: str) -> str:
        ts = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
        return f"{project_token}-cum-{ts}"

    def get_latest_active_cumulative_session(self, project_id: int) -> dict[str, Any] | None:
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(
                """
                SELECT * FROM project_run_cumulative_sessions
                WHERE project_id = %s AND is_active = TRUE
                ORDER BY started_at DESC, id DESC
                LIMIT 1
                """,
                (project_id,),
            )
            row = cur.fetchone()
            return self._lower_keys(dict(row)) if row else None

    def get_latest_preferred_cumulative_session(self, project_id: int) -> dict[str, Any] | None:
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(
                """
                SELECT * FROM project_run_cumulative_sessions
                WHERE project_id = %s
                ORDER BY is_active DESC, started_at DESC, id DESC
                LIMIT 1
                """,
                (project_id,),
            )
            row = cur.fetchone()
            return self._lower_keys(dict(row)) if row else None

    def create_cumulative_session(
        self, project_id: int, project_token: str, created_by_run_token: str | None = None,
    ) -> dict[str, Any]:
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cumulative_id = self._build_cumulative_id(project_token)
            cur.execute(
                """
                INSERT INTO project_run_cumulative_sessions (
                    project_run_cumulative_id, project_id, project_token,
                    status, started_at, created_by_run_token, last_run_token,
                    total_runs_in_session, is_active
                ) VALUES (%s, %s, %s, 'active', %s, %s, %s, 0, TRUE)
                """,
                (cumulative_id, project_id, project_token,
                 datetime.utcnow().isoformat(), created_by_run_token, created_by_run_token),
            )
            return {
                "project_run_cumulative_id": cumulative_id,
                "project_id": project_id,
                "project_token": project_token,
                "status": "active",
                "is_active": 1,
            }

    def attach_run_to_cumulative_session(
        self, project_id: int, project_token: str, run_token: str, force_new_session: bool = False,
    ) -> str:
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(
                """
                SELECT * FROM project_run_cumulative_sessions
                WHERE project_id = %s AND is_active = TRUE
                ORDER BY started_at DESC, id DESC
                LIMIT 1
                """,
                (project_id,),
            )
            active_row = cur.fetchone()

            if force_new_session and active_row:
                cur.execute(
                    """
                    UPDATE project_run_cumulative_sessions
                    SET status = 'closed', is_active = FALSE, completed_at = %s
                    WHERE id = %s
                    """,
                    (datetime.utcnow().isoformat(), active_row["ID"]),
                )
                active_row = None

            if active_row:
                cumulative_id = active_row["PROJECT_RUN_CUMULATIVE_ID"]
            else:
                cumulative_id = self._build_cumulative_id(project_token)
                cur.execute(
                    """
                    INSERT INTO project_run_cumulative_sessions (
                        project_run_cumulative_id, project_id, project_token,
                        status, started_at, created_by_run_token, last_run_token,
                        total_runs_in_session, is_active
                    ) VALUES (%s, %s, %s, 'active', %s, %s, %s, 0, TRUE)
                    """,
                    (cumulative_id, project_id, project_token,
                     datetime.utcnow().isoformat(), run_token, run_token),
                )

            cur.execute(
                """
                UPDATE project_run_cumulative_sessions
                SET last_run_token = %s,
                    total_runs_in_session = COALESCE(total_runs_in_session, 0) + 1,
                    is_active = TRUE,
                    status = 'active'
                WHERE project_id = %s AND project_run_cumulative_id = %s
                """,
                (run_token, project_id, cumulative_id),
            )
            return cumulative_id

    def close_cumulative_session(self, project_id: int, project_run_cumulative_id: str) -> bool:
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            cur.execute(
                """
                UPDATE project_run_cumulative_sessions
                SET status = 'complete', is_active = FALSE, completed_at = COALESCE(completed_at, %s)
                WHERE project_id = %s AND project_run_cumulative_id = %s
                """,
                (datetime.utcnow().isoformat(), project_id, project_run_cumulative_id),
            )
            return cur.rowcount > 0

    def close_latest_active_cumulative_session(self, project_id: int) -> dict[str, Any]:
        session = self.get_latest_active_cumulative_session(project_id)
        if not session:
            return {"success": True, "closed": False, "project_run_cumulative_id": None}
        closed = self.close_cumulative_session(project_id, session["project_run_cumulative_id"])
        return {
            "success": True,
            "closed": closed,
            "project_run_cumulative_id": session["project_run_cumulative_id"],
        }

    def get_max_scraped_page(self, project_id: int, project_run_cumulative_id: str | None = None) -> int | None:
        with get_connection() as conn:
            cur = conn.cursor(DictCursor)
            if project_run_cumulative_id:
                cur.execute(
                    "SELECT MAX(page_number) AS max_page FROM product_data WHERE project_id = %s AND project_run_cumulative_id = %s",
                    (project_id, project_run_cumulative_id),
                )
            else:
                cur.execute("SELECT MAX(page_number) AS max_page FROM product_data WHERE project_id = %s", (project_id,))
            row = cur.fetchone()
            max_page = row["MAX_PAGE"] if row else None
            return int(max_page) if max_page is not None else None

    @staticmethod
    def generate_next_page_url(base_url: str | None, current_page: int) -> str | None:
        """Build the resume start_url for the next page.

        IMPORTANT: when the input URL has no pagination marker yet (e.g. the project's
        bare website_url after a fresh manual Run), we MUST still produce a paginated
        URL — otherwise the caller passes no `start_url` to ParseHub and the new run
        falls back to the project's default page-1 URL, silently re-scraping pages
        already covered by the previous run instead of advancing.
        """
        if not base_url or not isinstance(base_url, str) or current_page < 1:
            return None
        next_page = current_page + 1
        url = base_url.strip()

        # Replace an existing pagination marker in-place when present.
        replacements: list[tuple[str, str]] = [
            (r"([?&])page=\d+", rf"\1page={next_page}"),
            (r"([?&])p=\d+", rf"\1p={next_page}"),
            (r"([?&])pages=\d+", rf"\1pages={next_page}"),
        ]
        for pattern, replacement in replacements:
            if re.search(pattern, url):
                return re.sub(pattern, replacement, url)
        if re.search(r"/page/\d+/?", url):
            return re.sub(r"/page/\d+/?", f"/page/{next_page}/", url)

        # No pagination marker present yet → append `page=N+1`. Pick the correct
        # separator depending on whether the URL already carries query params (e.g.
        # ?filter.p.vendor=...). Any trailing fragment (#...) is preserved.
        fragment = ""
        if "#" in url:
            url, fragment = url.split("#", 1)
            fragment = f"#{fragment}"
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}page={next_page}{fragment}"

    def prepare_resume_status(self, project_token: str) -> dict[str, Any]:
        result: dict[str, Any] = {
            "success": False,
            "resumable": False,
            "project_found": False,
            "metadata_found": False,
            "max_page_scraped": None,
            "total_pages": None,
            "next_page_number": None,
            "generated_next_page_url": None,
            "project_complete": False,
            "inconsistent": False,
            "active_project_run_cumulative_id": None,
            "message": "",
            "error": None,
            "metadata": None,
            "project_id": None,
        }

        project = self.get_project_by_token(project_token)
        if not project:
            result["error"] = f'Project with token "{project_token}" not found'
            result["message"] = "Cannot resume: project not found"
            return result

        result["project_found"] = True
        result["project_id"] = project.get("id")
        project_id = project.get("id")

        metadata = self.get_metadata_by_project_token(project_token)
        if not metadata:
            result["error"] = f"Metadata not found for project {project_token}"
            result["message"] = "Cannot resume: metadata not loaded for project"
            return result

        result["metadata_found"] = True
        result["metadata"] = metadata
        total_pages = int(metadata.get("total_pages") or 0)
        result["total_pages"] = total_pages
        if total_pages <= 0:
            result["error"] = "total_pages is missing or zero in metadata"
            result["message"] = "Cannot resume: metadata.total_pages is not set"
            return result

        active_session = self.get_latest_active_cumulative_session(project_id) if project_id else None
        active_cumulative_id = active_session["project_run_cumulative_id"] if active_session else None
        result["active_project_run_cumulative_id"] = active_cumulative_id

        if not active_cumulative_id:
            result["success"] = True
            result["resumable"] = False
            result["project_complete"] = False
            result["message"] = "No active cumulative run session found. Start a fresh manual Run before using Resume."
            return result

        max_page = self.get_max_scraped_page(project_id, active_cumulative_id) if project_id else None
        product_data_max_page = int(max_page) if max_page is not None else 0

        # ParseHub may report per-run-relative page numbers (each resume run starts
        # back at page 1 internally), so product_data alone can under-report cumulative
        # progress. Sum pages_scraped across completed runs in the *current* cumulative
        # session for an absolute, session-scoped progress signal that does NOT leak
        # values from previous sessions (unlike the legacy metadata.current_page_scraped).
        session_completed_pages = 0
        if project_id and active_cumulative_id:
            session_runs = self.get_runs_by_project(project_id, limit=200)
            completed_statuses = {"complete", "completed", "success", "succeeded"}
            for run in session_runs:
                if run.get("project_run_cumulative_id") != active_cumulative_id:
                    continue
                if str(run.get("status") or "").strip().lower() not in completed_statuses:
                    continue
                session_completed_pages += int(run.get("pages_scraped") or 0)

        max_page_num = max(product_data_max_page, session_completed_pages)
        # total_pages > 0 is enforced earlier; cap to avoid overshoot inconsistencies.
        max_page_num = min(max_page_num, total_pages)

        result["max_page_scraped"] = max_page_num

        if max_page_num >= total_pages:
            if max_page_num > total_pages:
                result["inconsistent"] = True
                result["project_complete"] = False
                result["resumable"] = False
                result["message"] = (
                    f"Data inconsistency detected: max scraped page ({max_page_num}) exceeds "
                    f"total_pages ({total_pages}). Verify metadata.total_pages is correct before resuming."
                )
                result["success"] = True
                return result
            result["project_complete"] = True
            result["message"] = f"Project is complete. All {total_pages} pages have been scraped (max scraped: page {max_page_num})"
            result["success"] = True
            return result

        next_page = max_page_num + 1
        result["next_page_number"] = next_page
        template_url = metadata.get("next_page_url") or metadata.get("website_url")
        if template_url:
            result["generated_next_page_url"] = self.generate_next_page_url(template_url, max_page_num)
        result["resumable"] = True
        result["success"] = True
        pages_remaining = total_pages - max_page_num
        result["message"] = f"Project is resumable from page {next_page}. Pages remaining: {pages_remaining}"
        return result

    # ------------------------------------------------------------------
    # Key normalization helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _lower_keys(d: dict) -> dict:
        """Snowflake DictCursor returns UPPER-CASE keys; normalize to lower."""
        return {k.lower(): v for k, v in d.items()}

    @staticmethod
    def _rows_to_dicts_lower(cursor) -> list[dict[str, Any]]:
        return [{k.lower(): v for k, v in row.items()} for row in cursor.fetchall()]

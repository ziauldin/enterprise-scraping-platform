"""
Snowflake DDL for all application tables.

Type mapping from SQLite:
    INTEGER PRIMARY KEY AUTOINCREMENT -> NUMBER(38,0) AUTOINCREMENT
    TEXT                              -> VARCHAR
    REAL                              -> FLOAT
    INTEGER (boolean-like)            -> BOOLEAN
    DEFAULT CURRENT_TIMESTAMP         -> DEFAULT CURRENT_TIMESTAMP()

Snowflake notes:
    - UNIQUE and FK constraints are advisory (not enforced); uniqueness is
      enforced at the application layer via MERGE INTO.
    - Traditional indexes don't exist; we use CLUSTER BY on the high-volume
      product_data table for micro-partition pruning.
"""

PROJECTS_DDL = """
CREATE TABLE IF NOT EXISTS projects (
    id              NUMBER(38,0) AUTOINCREMENT,
    token           VARCHAR      NOT NULL,
    title           VARCHAR      NOT NULL,
    owner_email     VARCHAR,
    main_site       VARCHAR,
    metadata_personal_project_id VARCHAR,
    metadata_update_date         VARCHAR,
    region          VARCHAR,
    country         VARCHAR,
    brand           VARCHAR,
    website_url     VARCHAR,
    next_page_url   VARCHAR,
    total_pages     NUMBER(38,0),
    total_products  NUMBER(38,0),
    current_page_scraped   NUMBER(38,0) DEFAULT 0,
    current_product_scraped NUMBER(38,0) DEFAULT 0,
    auto_resume_blocked    BOOLEAN      DEFAULT FALSE,
    auto_resume_max_page_checkpoint NUMBER(38,0),
    created_at      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    updated_at      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    UNIQUE (token),
    PRIMARY KEY (id)
)
COMMENT = 'ParseHub projects — one row per scraping project'
"""

RUNS_DDL = """
CREATE TABLE IF NOT EXISTS runs (
    id              NUMBER(38,0) AUTOINCREMENT,
    project_id      NUMBER(38,0) NOT NULL,
    run_token       VARCHAR      NOT NULL,
    status          VARCHAR      NOT NULL,
    pages_requested NUMBER(38,0) DEFAULT 1,
    pages_scraped   NUMBER(38,0) DEFAULT 0,
    data_ready      BOOLEAN      DEFAULT FALSE,
    start_time      VARCHAR,
    end_time        VARCHAR,
    duration_seconds NUMBER(38,0),
    project_run_cumulative_id VARCHAR,
    created_at      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    updated_at      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    UNIQUE (run_token),
    PRIMARY KEY (id),
    FOREIGN KEY (project_id) REFERENCES projects(id)
)
COMMENT = 'ParseHub run executions — one row per run'
"""

IMPORT_BATCHES_DDL = """
CREATE TABLE IF NOT EXISTS import_batches (
    id              NUMBER(38,0) AUTOINCREMENT,
    file_name       VARCHAR      NOT NULL,
    record_count    NUMBER(38,0) DEFAULT 0,
    status          VARCHAR      NOT NULL,
    uploaded_by     VARCHAR,
    upload_date     TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    PRIMARY KEY (id)
)
COMMENT = 'Excel/CSV import audit log'
"""

METADATA_DDL = """
CREATE TABLE IF NOT EXISTS metadata (
    personal_project_id VARCHAR NOT NULL,
    project_id_parsehub VARCHAR,
    project_name        VARCHAR NOT NULL,
    website_type        VARCHAR,
    last_run_data       VARCHAR,
    create_date         VARCHAR,
    update_date         VARCHAR,
    region              VARCHAR,
    country             VARCHAR,
    brand               VARCHAR,
    website_url         VARCHAR,
    next_page_url       VARCHAR,
    total_pages         NUMBER(38,0),
    total_products      NUMBER(38,0),
    current_page_scraped   NUMBER(38,0) DEFAULT 0,
    current_product_scraped NUMBER(38,0) DEFAULT 0,
    PRIMARY KEY (personal_project_id)
)
COMMENT = 'Business metadata keyed by personal project ID'
"""

PRODUCT_DATA_DDL = """
CREATE TABLE IF NOT EXISTS product_data (
    id              NUMBER(38,0) AUTOINCREMENT,
    project_id      NUMBER(38,0) NOT NULL,
    run_id          NUMBER(38,0),
    run_token       VARCHAR,
    project_run_cumulative_id VARCHAR,
    name            VARCHAR,
    part_number     VARCHAR,
    brand           VARCHAR,
    list_price      FLOAT,
    sale_price      FLOAT,
    case_unit_price FLOAT,
    country         VARCHAR,
    currency        VARCHAR,
    product_url     VARCHAR,
    page_number     NUMBER(38,0),
    extraction_date VARCHAR,
    data_source     VARCHAR,
    raw_json        VARCHAR,
    created_at      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    updated_at      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    PRIMARY KEY (id),
    UNIQUE (project_id, run_token, product_url, page_number),
    FOREIGN KEY (project_id) REFERENCES projects(id),
    FOREIGN KEY (run_id) REFERENCES runs(id)
)
CLUSTER BY (project_id, run_token)
COMMENT = 'Scraped product rows — high volume, clustered by project+run for pruning'
"""

PROJECT_RUN_CUMULATIVE_SESSIONS_DDL = """
CREATE TABLE IF NOT EXISTS project_run_cumulative_sessions (
    id              NUMBER(38,0) AUTOINCREMENT,
    project_run_cumulative_id VARCHAR NOT NULL,
    project_id      NUMBER(38,0) NOT NULL,
    project_token   VARCHAR      NOT NULL,
    status          VARCHAR      NOT NULL DEFAULT 'active',
    started_at      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    completed_at    TIMESTAMP_NTZ,
    created_by_run_token VARCHAR,
    last_run_token  VARCHAR,
    total_runs_in_session NUMBER(38,0) DEFAULT 0,
    is_active       BOOLEAN      DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE (project_run_cumulative_id),
    FOREIGN KEY (project_id) REFERENCES projects(id)
)
COMMENT = 'Groups multiple ParseHub runs into one cumulative scrape session'
"""

RUN_INGESTIONS_DDL = """
CREATE TABLE IF NOT EXISTS run_ingestions (
    run_token       VARCHAR      NOT NULL,
    project_id      NUMBER(38,0) NOT NULL,
    status          VARCHAR      NOT NULL,
    inserted_count  NUMBER(38,0) DEFAULT 0,
    last_error      VARCHAR,
    created_at      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    updated_at      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    PRIMARY KEY (run_token),
    FOREIGN KEY (project_id) REFERENCES projects(id)
)
COMMENT = 'Tracks run ingestion state for idempotent ingest/reconcile'
"""

AUTOMATION_LOCKS_DDL = """
CREATE TABLE IF NOT EXISTS automation_locks (
    lock_key        VARCHAR      NOT NULL,
    owner           VARCHAR      NOT NULL,
    expires_at      VARCHAR      NOT NULL,
    created_at      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    updated_at      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    PRIMARY KEY (lock_key)
)
COMMENT = 'DB-backed short-lived locks for automation actions'
"""

AUTOMATION_AUDIT_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS automation_audit_events (
    id                          NUMBER(38,0) AUTOINCREMENT,
    event_type                  VARCHAR      NOT NULL,
    project_id                  NUMBER(38,0),
    project_token               VARCHAR,
    run_token                   VARCHAR,
    project_run_cumulative_id   VARCHAR,
    status                      VARCHAR,
    message                     VARCHAR,
    details_json                VARCHAR,
    created_at                  TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    PRIMARY KEY (id),
    FOREIGN KEY (project_id) REFERENCES projects(id)
)
COMMENT = 'Automation event audit trail for scheduler/run workflows'
"""

SCHEDULED_PROJECT_RUNS_DDL = """
CREATE TABLE IF NOT EXISTS scheduled_project_runs (
    id                          NUMBER(38,0) AUTOINCREMENT,
    project_id                  NUMBER(38,0) NOT NULL,
    project_token               VARCHAR      NOT NULL,
    schedule_type               VARCHAR      NOT NULL DEFAULT 'one_time',
    recurrence_frequency        VARCHAR,
    recurrence_weekday          NUMBER(38,0),
    recurrence_day_of_month     NUMBER(38,0),
    local_time                  VARCHAR,
    scheduled_run_time_utc      VARCHAR      NOT NULL,
    scheduled_run_time_local    VARCHAR,
    timezone                    VARCHAR,
    is_active                   BOOLEAN      DEFAULT TRUE,
    status                      VARCHAR      NOT NULL DEFAULT 'scheduled',
    retry_count                 NUMBER(38,0) DEFAULT 0,
    max_retries                 NUMBER(38,0) DEFAULT 3,
    next_retry_time_utc         VARCHAR,
    last_claimed_occurrence_utc VARCHAR,
    run_token                   VARCHAR,
    error_message               VARCHAR,
    triggered_at                VARCHAR,
    completed_at                VARCHAR,
    created_at                  VARCHAR,
    updated_at                  VARCHAR,
    PRIMARY KEY (id),
    FOREIGN KEY (project_id) REFERENCES projects(id)
)
COMMENT = 'Scheduled one-time and recurring project run queue'
"""

SCHEDULED_RUN_STATUS_DDL = """
CREATE TABLE IF NOT EXISTS scheduled_run_status (
    id                  NUMBER(38,0) NOT NULL,
    project_token       VARCHAR      NOT NULL,
    scheduled_run_time  VARCHAR      NOT NULL,
    run_token           VARCHAR,
    status              VARCHAR      NOT NULL,
    retry_count         NUMBER(38,0) DEFAULT 0,
    max_retries         NUMBER(38,0) DEFAULT 3,
    error_message       VARCHAR,
    last_updated        VARCHAR,
    PRIMARY KEY (id)
)
COMMENT = 'Compatibility status table for UI schedule listing'
"""

STAGING_PRODUCT_DATA_DDL = """
CREATE TRANSIENT TABLE IF NOT EXISTS staging_product_data (
    project_id      NUMBER(38,0) NOT NULL,
    run_id          NUMBER(38,0),
    run_token       VARCHAR,
    project_run_cumulative_id VARCHAR,
    name            VARCHAR,
    part_number     VARCHAR,
    brand           VARCHAR,
    list_price      FLOAT,
    sale_price      FLOAT,
    case_unit_price FLOAT,
    country         VARCHAR,
    currency        VARCHAR,
    product_url     VARCHAR,
    page_number     NUMBER(38,0),
    extraction_date VARCHAR,
    data_source     VARCHAR,
    raw_json        VARCHAR,
    created_at      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    updated_at      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
)
COMMENT = 'Transient staging table for bulk product data loads — no Fail-safe cost'
"""

ALL_TABLE_DDL = [
    ("projects", PROJECTS_DDL),
    ("runs", RUNS_DDL),
    ("import_batches", IMPORT_BATCHES_DDL),
    ("metadata", METADATA_DDL),
    ("product_data", PRODUCT_DATA_DDL),
    ("project_run_cumulative_sessions", PROJECT_RUN_CUMULATIVE_SESSIONS_DDL),
    ("run_ingestions", RUN_INGESTIONS_DDL),
    ("automation_locks", AUTOMATION_LOCKS_DDL),
    ("automation_audit_events", AUTOMATION_AUDIT_EVENTS_DDL),
    ("scheduled_project_runs", SCHEDULED_PROJECT_RUNS_DDL),
    ("scheduled_run_status", SCHEDULED_RUN_STATUS_DDL),
]

MIGRATION_TABLE_DDL = ALL_TABLE_DDL + [
    ("staging_product_data", STAGING_PRODUCT_DATA_DDL),
]


def _ensure_projects_auto_resume_columns(cursor) -> None:
    """Add auto-resume columns if missing (schemas created before they existed in PROJECTS_DDL).

    Snowflake does not allow IF NOT EXISTS together with DEFAULT on ADD COLUMN.
    """
    cursor.execute(
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS auto_resume_blocked BOOLEAN"
    )
    cursor.execute(
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS auto_resume_max_page_checkpoint NUMBER(38,0)"
    )


def _ensure_metadata_website_type_column(cursor) -> None:
    """Add website_type if missing on pre-existing metadata table."""
    cursor.execute(
        "ALTER TABLE metadata ADD COLUMN IF NOT EXISTS website_type VARCHAR"
    )


def create_all_tables(cursor):
    """Execute DDL for every application table."""
    for name, ddl in ALL_TABLE_DDL:
        cursor.execute(ddl)
    _ensure_projects_auto_resume_columns(cursor)
    _ensure_metadata_website_type_column(cursor)


def create_all_tables_with_staging(cursor):
    """Execute DDL for application tables plus transient staging table."""
    for name, ddl in MIGRATION_TABLE_DDL:
        cursor.execute(ddl)
    _ensure_projects_auto_resume_columns(cursor)
    _ensure_metadata_website_type_column(cursor)

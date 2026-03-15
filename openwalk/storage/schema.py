"""Database schema definitions and migration system for OpenWalk.

Uses SQLite PRAGMA user_version for schema versioning.
All tables are created in migration v0→v1 (initial schema).
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiosqlite

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# Table definitions
# ---------------------------------------------------------------------------

SESSIONS_TABLE = """\
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Session timing
    started_at TEXT NOT NULL,
    ended_at TEXT,

    -- Session totals (computed from samples)
    total_steps INTEGER,
    total_seconds INTEGER,
    distance_raw INTEGER,
    distance_miles REAL,
    calories INTEGER,
    max_speed INTEGER,
    avg_speed REAL,

    -- Sync state machine
    sync_state TEXT NOT NULL DEFAULT 'RECORDING',
    sync_attempts INTEGER NOT NULL DEFAULT 0,
    sync_last_attempt_at TEXT,
    sync_last_error TEXT,
    sync_completed_at TEXT,

    -- HealthKit references
    hk_workout_uuid TEXT,
    hk_steps_uuid TEXT,
    hk_distance_uuid TEXT,
    hk_calories_uuid TEXT,

    -- Metadata
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

SAMPLES_TABLE = """\
CREATE TABLE IF NOT EXISTS samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,

    -- Timestamp
    captured_at TEXT NOT NULL,

    -- Telemetry fields
    steps INTEGER,
    distance_raw INTEGER,
    calories_raw INTEGER,
    elapsed_seconds INTEGER,
    speed INTEGER,
    belt_state INTEGER,

    -- Raw data preservation
    raw_hex TEXT
);
"""

SYNC_CHUNKS_TABLE = """\
CREATE TABLE IF NOT EXISTS sync_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,

    -- Chunk identification
    chunk_index INTEGER NOT NULL,
    chunk_start TEXT NOT NULL,
    chunk_end TEXT NOT NULL,

    -- Delta values for this 60-second window
    steps_delta INTEGER NOT NULL,
    distance_delta_raw INTEGER NOT NULL,
    calories_delta INTEGER NOT NULL,

    -- Cumulative values at chunk end
    steps_cumulative INTEGER NOT NULL,
    distance_cumulative_raw INTEGER NOT NULL,
    calories_cumulative INTEGER NOT NULL,

    -- Sync state for this chunk
    sync_state TEXT NOT NULL DEFAULT 'PENDING',
    sync_attempts INTEGER NOT NULL DEFAULT 0,
    sync_last_error TEXT,

    -- HealthKit references
    hk_steps_uuid TEXT,
    hk_distance_uuid TEXT,
    hk_calories_uuid TEXT,

    -- Metadata
    created_at TEXT NOT NULL DEFAULT (datetime('now')),

    -- Prevent duplicate chunks
    UNIQUE(session_id, chunk_index)
);
"""

ERROR_LOG_TABLE = """\
CREATE TABLE IF NOT EXISTS error_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES sessions(id) ON DELETE SET NULL,

    -- Error details
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    error_type TEXT NOT NULL,
    error_message TEXT,

    -- Raw data that caused the error
    raw_hex TEXT,
    raw_length INTEGER,
    expected_length INTEGER,

    -- Context
    packet_type INTEGER,
    connection_state TEXT
);
"""

# ---------------------------------------------------------------------------
# Indexes
# ---------------------------------------------------------------------------

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_sessions_sync_state ON sessions(sync_state);",
    "CREATE INDEX IF NOT EXISTS idx_sessions_started_at ON sessions(started_at);",
    "CREATE INDEX IF NOT EXISTS idx_samples_session_id ON samples(session_id);",
    "CREATE INDEX IF NOT EXISTS idx_samples_captured_at ON samples(session_id, captured_at);",
    (
        "CREATE INDEX IF NOT EXISTS idx_sync_chunks_pending ON sync_chunks(sync_state) "
        "WHERE sync_state = 'PENDING';"
    ),
    "CREATE INDEX IF NOT EXISTS idx_sync_chunks_session_id ON sync_chunks(session_id);",
    "CREATE INDEX IF NOT EXISTS idx_error_log_session_id ON error_log(session_id);",
    "CREATE INDEX IF NOT EXISTS idx_error_log_timestamp ON error_log(timestamp);",
]


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------


async def _get_schema_version(db: "aiosqlite.Connection") -> int:
    """Get current schema version from database."""
    async with db.execute("PRAGMA user_version") as cursor:
        row = await cursor.fetchone()
        return row[0] if row else 0


async def _set_schema_version(db: "aiosqlite.Connection", version: int) -> None:
    """Set schema version in database."""
    await db.execute(f"PRAGMA user_version = {version}")


async def _migrate_v0_to_v1(db: "aiosqlite.Connection") -> None:
    """Initial schema creation: all 4 tables and indexes."""
    await db.execute(SESSIONS_TABLE)
    await db.execute(SAMPLES_TABLE)
    await db.execute(SYNC_CHUNKS_TABLE)
    await db.execute(ERROR_LOG_TABLE)
    for index_sql in INDEXES:
        await db.execute(index_sql)


# Ordered list of migrations: (target_version, migration_function)
_MIGRATIONS = [
    (1, _migrate_v0_to_v1),
]


async def migrate_database(db: "aiosqlite.Connection") -> None:
    """Apply all pending schema migrations.

    Safe to call on every startup — skips already-applied migrations.
    """
    current = await _get_schema_version(db)

    for target_version, migration_fn in _MIGRATIONS:
        if current < target_version:
            logger.info("Applying migration to schema version %d", target_version)
            await migration_fn(db)
            await _set_schema_version(db, target_version)
            await db.commit()
            current = target_version

    if current == SCHEMA_VERSION:
        logger.debug("Database schema is up to date (version %d)", current)

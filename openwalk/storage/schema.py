"""Database schema definitions for OpenWalk.

Uses SQLite PRAGMA user_version for schema versioning.
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

    -- Session lifecycle state: RECORDING → COMPLETED
    state TEXT NOT NULL DEFAULT 'RECORDING',

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
    "CREATE INDEX IF NOT EXISTS idx_sessions_started_at ON sessions(started_at);",
    "CREATE INDEX IF NOT EXISTS idx_samples_session_id ON samples(session_id);",
    "CREATE INDEX IF NOT EXISTS idx_samples_captured_at ON samples(session_id, captured_at);",
    "CREATE INDEX IF NOT EXISTS idx_error_log_session_id ON error_log(session_id);",
    "CREATE INDEX IF NOT EXISTS idx_error_log_timestamp ON error_log(timestamp);",
]


# ---------------------------------------------------------------------------
# Schema initialization
# ---------------------------------------------------------------------------


async def _get_schema_version(db: "aiosqlite.Connection") -> int:
    """Get current schema version from database."""
    async with db.execute("PRAGMA user_version") as cursor:
        row = await cursor.fetchone()
        return row[0] if row else 0


async def _set_schema_version(db: "aiosqlite.Connection", version: int) -> None:
    """Set schema version in database."""
    await db.execute(f"PRAGMA user_version = {version}")


async def _create_schema(db: "aiosqlite.Connection") -> None:
    """Create all tables and indexes."""
    await db.execute(SESSIONS_TABLE)
    await db.execute(SAMPLES_TABLE)
    await db.execute(ERROR_LOG_TABLE)
    for index_sql in INDEXES:
        await db.execute(index_sql)


async def migrate_database(db: "aiosqlite.Connection") -> None:
    """Initialize or verify database schema.

    Safe to call on every startup — skips if already at current version.
    """
    current = await _get_schema_version(db)

    if current == 0:
        logger.info("Creating database schema (version %d)", SCHEMA_VERSION)
        await _create_schema(db)
        await _set_schema_version(db, SCHEMA_VERSION)
        await db.commit()
    elif current == SCHEMA_VERSION:
        logger.debug("Database schema is up to date (version %d)", current)
    else:
        logger.warning(
            "Database schema version %d does not match expected %d — "
            "delete ~/.openwalk/openwalk.db to reset",
            current,
            SCHEMA_VERSION,
        )

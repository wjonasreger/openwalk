"""Sync chunk CRUD operations for HealthKit incremental sync.

Manages 60-second chunks of session data for HealthKit synchronization.
Each chunk represents a time window with step, distance, and calorie deltas.
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openwalk.storage.database import Database

logger = logging.getLogger(__name__)


@dataclass
class ChunkRow:
    """Typed representation of a sync_chunks database row."""

    id: int
    session_id: int
    chunk_index: int
    chunk_start: str
    chunk_end: str
    steps_delta: int
    distance_delta_raw: int
    calories_delta: int
    steps_cumulative: int
    distance_cumulative_raw: int
    calories_cumulative: int
    sync_state: str
    sync_attempts: int
    sync_last_error: str | None
    hk_steps_uuid: str | None
    hk_distance_uuid: str | None
    hk_calories_uuid: str | None
    created_at: str

    @classmethod
    def from_row(cls, row: Any) -> "ChunkRow":
        """Create ChunkRow from an aiosqlite.Row."""
        return cls(
            id=row["id"],
            session_id=row["session_id"],
            chunk_index=row["chunk_index"],
            chunk_start=row["chunk_start"],
            chunk_end=row["chunk_end"],
            steps_delta=row["steps_delta"],
            distance_delta_raw=row["distance_delta_raw"],
            calories_delta=row["calories_delta"],
            steps_cumulative=row["steps_cumulative"],
            distance_cumulative_raw=row["distance_cumulative_raw"],
            calories_cumulative=row["calories_cumulative"],
            sync_state=row["sync_state"],
            sync_attempts=row["sync_attempts"],
            sync_last_error=row["sync_last_error"],
            hk_steps_uuid=row["hk_steps_uuid"],
            hk_distance_uuid=row["hk_distance_uuid"],
            hk_calories_uuid=row["hk_calories_uuid"],
            created_at=row["created_at"],
        )


class ChunkManager:
    """Sync chunk CRUD operations.

    Args:
        db: Connected Database instance.
    """

    def __init__(self, db: "Database") -> None:
        self.db = db

    async def insert_chunk(
        self,
        session_id: int,
        chunk_index: int,
        chunk_start: str,
        chunk_end: str,
        steps_delta: int,
        distance_delta_raw: int,
        calories_delta: int,
        steps_cumulative: int,
        distance_cumulative_raw: int,
        calories_cumulative: int,
    ) -> int:
        """Insert a new sync chunk.

        Returns:
            The new chunk's row ID.

        Raises:
            aiosqlite.IntegrityError: If (session_id, chunk_index) already exists.
        """
        cursor = await self.db.execute(
            """\
            INSERT INTO sync_chunks
                (session_id, chunk_index, chunk_start, chunk_end,
                 steps_delta, distance_delta_raw, calories_delta,
                 steps_cumulative, distance_cumulative_raw, calories_cumulative)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                chunk_index,
                chunk_start,
                chunk_end,
                steps_delta,
                distance_delta_raw,
                calories_delta,
                steps_cumulative,
                distance_cumulative_raw,
                calories_cumulative,
            ),
        )
        chunk_id = cursor.lastrowid
        assert chunk_id is not None
        logger.debug(
            "Inserted chunk %d (session %d, index %d)", chunk_id, session_id, chunk_index
        )
        return chunk_id

    async def get_chunks(self, session_id: int) -> list[ChunkRow]:
        """Get all chunks for a session, ordered by chunk_index."""
        rows = await self.db.fetchall(
            "SELECT * FROM sync_chunks WHERE session_id = ? ORDER BY chunk_index ASC",
            (session_id,),
        )
        return [ChunkRow.from_row(r) for r in rows]

    async def get_pending_chunks(self, session_id: int) -> list[ChunkRow]:
        """Get chunks that need to be synced (PENDING state)."""
        rows = await self.db.fetchall(
            """\
            SELECT * FROM sync_chunks
            WHERE session_id = ? AND sync_state = 'PENDING'
            ORDER BY chunk_index ASC
            """,
            (session_id,),
        )
        return [ChunkRow.from_row(r) for r in rows]

    async def get_failed_chunks(self, session_id: int) -> list[ChunkRow]:
        """Get chunks that failed to sync."""
        rows = await self.db.fetchall(
            """\
            SELECT * FROM sync_chunks
            WHERE session_id = ? AND sync_state = 'FAILED'
            ORDER BY chunk_index ASC
            """,
            (session_id,),
        )
        return [ChunkRow.from_row(r) for r in rows]

    async def get_chunk_by_index(
        self, session_id: int, chunk_index: int
    ) -> ChunkRow | None:
        """Get a specific chunk by session ID and index."""
        row = await self.db.fetchone(
            "SELECT * FROM sync_chunks WHERE session_id = ? AND chunk_index = ?",
            (session_id, chunk_index),
        )
        return ChunkRow.from_row(row) if row else None

    async def mark_synced(
        self,
        chunk_id: int,
        *,
        hk_steps_uuid: str,
        hk_distance_uuid: str,
        hk_calories_uuid: str,
    ) -> None:
        """Mark a chunk as successfully synced with HealthKit UUIDs."""
        await self.db.execute(
            """\
            UPDATE sync_chunks
            SET sync_state = 'SYNCED',
                hk_steps_uuid = ?,
                hk_distance_uuid = ?,
                hk_calories_uuid = ?,
                sync_last_error = NULL
            WHERE id = ?
            """,
            (hk_steps_uuid, hk_distance_uuid, hk_calories_uuid, chunk_id),
        )
        logger.debug("Chunk %d marked as SYNCED", chunk_id)

    async def mark_failed(self, chunk_id: int, error: str) -> None:
        """Mark a chunk as failed to sync."""
        await self.db.execute(
            """\
            UPDATE sync_chunks
            SET sync_state = 'FAILED',
                sync_attempts = sync_attempts + 1,
                sync_last_error = ?
            WHERE id = ?
            """,
            (error, chunk_id),
        )
        logger.debug("Chunk %d marked as FAILED: %s", chunk_id, error)

    async def get_chunk_count(self, session_id: int) -> int:
        """Get the number of chunks for a session."""
        row = await self.db.fetchone(
            "SELECT COUNT(*) as cnt FROM sync_chunks WHERE session_id = ?",
            (session_id,),
        )
        return row["cnt"] if row else 0

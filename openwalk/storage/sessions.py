"""Session CRUD operations and state machine for OpenWalk.

Manages the session lifecycle: RECORDING → COMPLETED → SYNC_PENDING → SYNCED.
Includes startup recovery for sessions interrupted by crashes.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openwalk.storage.database import Database

logger = logging.getLogger(__name__)


class SessionState(Enum):
    """Session sync state machine states."""

    RECORDING = "RECORDING"
    COMPLETED = "COMPLETED"
    SYNC_PENDING = "SYNC_PENDING"
    SYNC_FAILED = "SYNC_FAILED"
    SYNCED = "SYNCED"


# Valid state transitions: {current_state: [allowed_next_states]}
_VALID_TRANSITIONS: dict[SessionState, list[SessionState]] = {
    SessionState.RECORDING: [SessionState.COMPLETED],
    SessionState.COMPLETED: [SessionState.SYNC_PENDING],
    SessionState.SYNC_PENDING: [SessionState.SYNCED, SessionState.SYNC_FAILED],
    SessionState.SYNC_FAILED: [SessionState.SYNC_PENDING],
    SessionState.SYNCED: [],  # Terminal state
}


@dataclass
class SessionRow:
    """Typed representation of a session database row."""

    id: int
    started_at: str
    ended_at: str | None
    total_steps: int | None
    total_seconds: int | None
    distance_raw: int | None
    distance_miles: float | None
    calories: int | None
    max_speed: int | None
    avg_speed: float | None
    sync_state: str
    sync_attempts: int
    sync_last_attempt_at: str | None
    sync_last_error: str | None
    sync_completed_at: str | None
    hk_workout_uuid: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: Any) -> "SessionRow":
        """Create SessionRow from an aiosqlite.Row."""
        return cls(
            id=row["id"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            total_steps=row["total_steps"],
            total_seconds=row["total_seconds"],
            distance_raw=row["distance_raw"],
            distance_miles=row["distance_miles"],
            calories=row["calories"],
            max_speed=row["max_speed"],
            avg_speed=row["avg_speed"],
            sync_state=row["sync_state"],
            sync_attempts=row["sync_attempts"],
            sync_last_attempt_at=row["sync_last_attempt_at"],
            sync_last_error=row["sync_last_error"],
            sync_completed_at=row["sync_completed_at"],
            hk_workout_uuid=row["hk_workout_uuid"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class SessionManager:
    """Session CRUD and state machine operations.

    Args:
        db: Connected Database instance.
    """

    def __init__(self, db: "Database") -> None:
        self.db = db

    async def create_session(self) -> int:
        """Create a new session in RECORDING state.

        Returns:
            The new session's ID.
        """
        now = datetime.now().isoformat()
        cursor = await self.db.execute(
            "INSERT INTO sessions (started_at, sync_state) VALUES (?, ?)",
            (now, SessionState.RECORDING.value),
        )
        session_id = cursor.lastrowid
        assert session_id is not None
        logger.info("Created session %d", session_id)
        return session_id

    async def get_session(self, session_id: int) -> SessionRow | None:
        """Get a session by ID.

        Returns:
            SessionRow if found, None otherwise.
        """
        row = await self.db.fetchone("SELECT * FROM sessions WHERE id = ?", (session_id,))
        return SessionRow.from_row(row) if row else None

    async def get_sessions_by_state(self, state: SessionState) -> list[SessionRow]:
        """Get all sessions in the given state."""
        rows = await self.db.fetchall(
            "SELECT * FROM sessions WHERE sync_state = ? ORDER BY started_at DESC",
            (state.value,),
        )
        return [SessionRow.from_row(r) for r in rows]

    async def get_recent_sessions(self, limit: int = 10) -> list[SessionRow]:
        """Get the most recent sessions.

        Args:
            limit: Maximum number of sessions to return.

        Returns:
            List of sessions ordered by started_at descending.
        """
        rows = await self.db.fetchall(
            "SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?",
            (limit,),
        )
        return [SessionRow.from_row(r) for r in rows]

    async def update_totals(
        self,
        session_id: int,
        *,
        total_steps: int,
        total_seconds: int,
        distance_raw: int,
        distance_miles: float,
        calories: int,
        max_speed: int,
        avg_speed: float,
    ) -> None:
        """Update session running totals (called periodically during recording)."""
        await self.db.execute(
            """\
            UPDATE sessions
            SET total_steps = ?, total_seconds = ?, distance_raw = ?,
                distance_miles = ?, calories = ?, max_speed = ?,
                avg_speed = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                total_steps,
                total_seconds,
                distance_raw,
                distance_miles,
                calories,
                max_speed,
                avg_speed,
                session_id,
            ),
        )

    async def finalize_session(self, session_id: int) -> None:
        """Finalize a RECORDING session: compute totals from last sample, transition to COMPLETED.

        If the session has no samples, it is deleted instead.
        """
        # Get last sample for this session
        last_sample = await self.db.fetchone(
            "SELECT * FROM samples WHERE session_id = ? ORDER BY captured_at DESC LIMIT 1",
            (session_id,),
        )

        if last_sample is None:
            # No data captured — discard empty session
            await self.db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            logger.info("Deleted empty session %d", session_id)
            return

        # Compute aggregates from samples
        stats = await self.db.fetchone(
            """\
            SELECT MAX(speed) as max_speed,
                   AVG(CASE WHEN belt_state = 1 THEN speed END) as avg_speed
            FROM samples WHERE session_id = ?
            """,
            (session_id,),
        )

        await self.db.execute(
            """\
            UPDATE sessions
            SET ended_at = ?,
                total_steps = ?,
                total_seconds = ?,
                distance_raw = ?,
                distance_miles = ?,
                calories = ?,
                max_speed = ?,
                avg_speed = ?,
                sync_state = ?,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                last_sample["captured_at"],
                last_sample["steps"],
                last_sample["elapsed_seconds"],
                last_sample["distance_raw"],
                (last_sample["distance_raw"] or 0) / 100.0,
                last_sample["calories_raw"],
                stats["max_speed"] if stats else None,
                stats["avg_speed"] if stats else None,
                SessionState.COMPLETED.value,
                session_id,
            ),
        )
        logger.info("Finalized session %d", session_id)

    async def transition_state(
        self,
        session_id: int,
        new_state: SessionState,
        *,
        error: str | None = None,
        hk_workout_uuid: str | None = None,
    ) -> None:
        """Transition a session to a new state, validating the transition.

        Args:
            session_id: Session to transition.
            new_state: Target state.
            error: Error message (for SYNC_FAILED transitions).
            hk_workout_uuid: HealthKit workout UUID (for SYNCED transitions).

        Raises:
            ValueError: If the transition is not valid.
        """
        session = await self.get_session(session_id)
        if session is None:
            raise ValueError(f"Session {session_id} not found")

        current = SessionState(session.sync_state)
        allowed = _VALID_TRANSITIONS.get(current, [])

        if new_state not in allowed:
            raise ValueError(
                f"Invalid transition: {current.value} → {new_state.value}. "
                f"Allowed: {[s.value for s in allowed]}"
            )

        now = datetime.now().isoformat()

        if new_state == SessionState.SYNC_PENDING:
            await self.db.execute(
                """\
                UPDATE sessions
                SET sync_state = ?, sync_attempts = sync_attempts + 1,
                    sync_last_attempt_at = ?, updated_at = datetime('now')
                WHERE id = ?
                """,
                (new_state.value, now, session_id),
            )
        elif new_state == SessionState.SYNCED:
            await self.db.execute(
                """\
                UPDATE sessions
                SET sync_state = ?, sync_completed_at = ?,
                    hk_workout_uuid = ?, sync_last_error = NULL,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (new_state.value, now, hk_workout_uuid, session_id),
            )
        elif new_state == SessionState.SYNC_FAILED:
            await self.db.execute(
                """\
                UPDATE sessions
                SET sync_state = ?, sync_last_error = ?,
                    sync_last_attempt_at = ?, updated_at = datetime('now')
                WHERE id = ?
                """,
                (new_state.value, error, now, session_id),
            )
        else:
            await self.db.execute(
                """\
                UPDATE sessions
                SET sync_state = ?, updated_at = datetime('now')
                WHERE id = ?
                """,
                (new_state.value, session_id),
            )

        logger.info("Session %d: %s → %s", session_id, current.value, new_state.value)

    async def recover_interrupted(self) -> int:
        """Recover sessions stuck in RECORDING state (crash recovery).

        Called on startup. Finalizes sessions that have samples,
        deletes sessions with no samples.

        Returns:
            Number of sessions recovered.
        """
        recording = await self.get_sessions_by_state(SessionState.RECORDING)
        recovered = 0

        for session in recording:
            sample_count = await self.db.fetchone(
                "SELECT COUNT(*) as cnt FROM samples WHERE session_id = ?",
                (session.id,),
            )
            count = sample_count["cnt"] if sample_count else 0

            if count > 0:
                await self.finalize_session(session.id)
                logger.warning("Recovered interrupted session %d (%d samples)", session.id, count)
                recovered += 1
            else:
                await self.db.execute("DELETE FROM sessions WHERE id = ?", (session.id,))
                logger.info("Discarded empty interrupted session %d", session.id)

        return recovered

    async def recover_stale_sync_pending(self, max_age_hours: int = 1) -> int:
        """Move SYNC_PENDING sessions older than max_age_hours to SYNC_FAILED.

        Called on startup to recover sessions stuck in SYNC_PENDING state
        (e.g., if the app crashed mid-sync).

        Args:
            max_age_hours: Maximum age in hours before a SYNC_PENDING session
                is considered stale.

        Returns:
            Number of sessions recovered.
        """
        pending = await self.get_sessions_by_state(SessionState.SYNC_PENDING)
        cutoff = (datetime.now() - timedelta(hours=max_age_hours)).isoformat()
        recovered = 0

        for session in pending:
            attempt_at = session.sync_last_attempt_at
            if attempt_at is not None and attempt_at < cutoff:
                await self.db.execute(
                    """\
                    UPDATE sessions
                    SET sync_state = ?, sync_last_error = ?,
                        updated_at = datetime('now')
                    WHERE id = ?
                    """,
                    (SessionState.SYNC_FAILED.value, "Sync timed out", session.id),
                )
                logger.warning(
                    "Recovered stale SYNC_PENDING session %d (last attempt: %s)",
                    session.id,
                    attempt_at,
                )
                recovered += 1

        return recovered

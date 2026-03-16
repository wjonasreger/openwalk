"""Session CRUD operations and state machine for OpenWalk.

Manages the session lifecycle: RECORDING → COMPLETED.
Includes startup recovery for sessions interrupted by crashes.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openwalk.storage.database import Database

logger = logging.getLogger(__name__)


class SessionState(Enum):
    """Session lifecycle states."""

    RECORDING = "RECORDING"
    COMPLETED = "COMPLETED"


# Valid state transitions: {current_state: [allowed_next_states]}
_VALID_TRANSITIONS: dict[SessionState, list[SessionState]] = {
    SessionState.RECORDING: [SessionState.COMPLETED],
    SessionState.COMPLETED: [],  # Terminal state
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
    state: str
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
            state=row["state"],
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
            "INSERT INTO sessions (started_at, state) VALUES (?, ?)",
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
            "SELECT * FROM sessions WHERE state = ? ORDER BY started_at DESC",
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
        """Mark a RECORDING session as COMPLETED.

        Expects that update_totals() was already called by the orchestrator.
        Only sets ended_at and state. Deletes empty sessions with no samples.
        """
        last_sample = await self.db.fetchone(
            "SELECT captured_at FROM samples"
            " WHERE session_id = ? ORDER BY captured_at DESC LIMIT 1",
            (session_id,),
        )

        if last_sample is None:
            await self.db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            logger.info("Deleted empty session %d", session_id)
            return

        await self.db.execute(
            """\
            UPDATE sessions
            SET ended_at = ?, state = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (last_sample["captured_at"], SessionState.COMPLETED.value, session_id),
        )
        logger.info("Finalized session %d", session_id)

    async def compute_totals_from_samples(self, session_id: int) -> None:
        """Compute session totals from sample data (used for crash recovery).

        Derives session-relative steps/distance from first and last samples.
        """
        stats = await self.db.fetchone(
            """\
            SELECT
                MIN(steps) as first_steps,
                MAX(steps) as last_steps,
                MIN(distance_raw) as first_dist,
                MAX(distance_raw) as last_dist,
                MAX(speed) as max_speed,
                AVG(CASE WHEN belt_state = 1 THEN speed END) as avg_speed,
                MIN(captured_at) as first_at,
                MAX(captured_at) as last_at
            FROM samples WHERE session_id = ?
            """,
            (session_id,),
        )

        if stats is None or stats["first_at"] is None:
            return

        total_steps = (stats["last_steps"] or 0) - (stats["first_steps"] or 0)
        distance_raw = (stats["last_dist"] or 0) - (stats["first_dist"] or 0)

        first_at = datetime.fromisoformat(stats["first_at"])
        last_at = datetime.fromisoformat(stats["last_at"])
        total_seconds = int((last_at - first_at).total_seconds())

        avg_speed_raw = stats["avg_speed"] or 0
        avg_speed_mph = round(avg_speed_raw / 10.0, 2)

        await self.db.execute(
            """\
            UPDATE sessions
            SET total_steps = ?, total_seconds = ?, distance_raw = ?,
                distance_miles = ?, max_speed = ?, avg_speed = ?,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                total_steps,
                total_seconds,
                distance_raw,
                distance_raw / 100.0,
                stats["max_speed"],
                avg_speed_mph,
                session_id,
            ),
        )
        logger.info("Computed totals from samples for session %d", session_id)

    async def transition_state(
        self,
        session_id: int,
        new_state: SessionState,
    ) -> None:
        """Transition a session to a new state, validating the transition.

        Args:
            session_id: Session to transition.
            new_state: Target state.

        Raises:
            ValueError: If the transition is not valid.
        """
        session = await self.get_session(session_id)
        if session is None:
            raise ValueError(f"Session {session_id} not found")

        current = SessionState(session.state)
        allowed = _VALID_TRANSITIONS.get(current, [])

        if new_state not in allowed:
            raise ValueError(
                f"Invalid transition: {current.value} → {new_state.value}. "
                f"Allowed: {[s.value for s in allowed]}"
            )

        await self.db.execute(
            """\
            UPDATE sessions
            SET state = ?, updated_at = datetime('now')
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
                await self.compute_totals_from_samples(session.id)
                await self.finalize_session(session.id)
                logger.warning("Recovered interrupted session %d (%d samples)", session.id, count)
                recovered += 1
            else:
                await self.db.execute("DELETE FROM sessions WHERE id = ?", (session.id,))
                logger.info("Discarded empty interrupted session %d", session.id)

        return recovered

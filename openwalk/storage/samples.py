"""Sample insertion and query operations for OpenWalk.

Handles immediate persistence of BLE DATA messages to SQLite
and error logging for truncated/invalid frames.
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from openwalk.protocol.messages import DataMessage, TruncatedFrame

if TYPE_CHECKING:
    from openwalk.storage.database import Database

logger = logging.getLogger(__name__)


@dataclass
class SampleRow:
    """Typed representation of a sample database row."""

    id: int
    session_id: int
    captured_at: str
    steps: int | None
    distance_raw: int | None
    calories_raw: int | None
    elapsed_seconds: int | None
    speed: int | None
    belt_state: int | None
    raw_hex: str | None

    @classmethod
    def from_row(cls, row: Any) -> "SampleRow":
        """Create SampleRow from an aiosqlite.Row."""
        return cls(
            id=row["id"],
            session_id=row["session_id"],
            captured_at=row["captured_at"],
            steps=row["steps"],
            distance_raw=row["distance_raw"],
            calories_raw=row["calories_raw"],
            elapsed_seconds=row["elapsed_seconds"],
            speed=row["speed"],
            belt_state=row["belt_state"],
            raw_hex=row["raw_hex"],
        )


class SampleManager:
    """Sample insertion and query operations.

    Args:
        db: Connected Database instance.
    """

    def __init__(self, db: "Database") -> None:
        self.db = db

    async def insert_sample(
        self,
        session_id: int,
        msg: DataMessage,
        cumulative_steps: int | None = None,
        cumulative_belt_revs: int | None = None,
    ) -> int:
        """Insert a DATA message as a sample row.

        Writes immediately and commits for crash resilience.

        Args:
            session_id: Parent session ID.
            msg: Parsed DataMessage from protocol parser.
            cumulative_steps: Total steps from SessionCounters (if available).
            cumulative_belt_revs: Total belt revs from SessionCounters (unused in schema,
                reserved for future use).

        Returns:
            The new sample's row ID.
        """
        # Use cumulative steps if provided, otherwise raw value from message
        steps = cumulative_steps if cumulative_steps is not None else msg.steps

        cursor = await self.db.execute(
            """\
            INSERT INTO samples
                (session_id, captured_at, steps, distance_raw, calories_raw,
                 elapsed_seconds, speed, belt_state, raw_hex)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                msg.timestamp.isoformat(),
                steps,
                msg.distance_raw,
                None,  # calories_raw: computed by caller, not in protocol
                msg.motor_pulses,  # motor_pulses stored as elapsed_seconds placeholder
                msg.speed,
                msg.belt_state,
                msg.raw_hex,
            ),
        )
        sample_id = cursor.lastrowid
        assert sample_id is not None
        return sample_id

    async def insert_error(
        self,
        session_id: int | None,
        frame: TruncatedFrame,
        connection_state: str | None = None,
    ) -> int:
        """Log a truncated or invalid frame to the error_log table.

        Args:
            session_id: Parent session ID (may be None if no active session).
            frame: TruncatedFrame from protocol parser.
            connection_state: Current BLE connection state string.

        Returns:
            The new error_log row ID.
        """
        cursor = await self.db.execute(
            """\
            INSERT INTO error_log
                (session_id, timestamp, error_type, error_message,
                 raw_hex, raw_length, expected_length, packet_type, connection_state)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                frame.timestamp.isoformat(),
                "TRUNCATED_FRAME",
                f"Expected {frame.expected_size} bytes, got {frame.actual_size} ({frame.variant})",
                frame.raw_hex,
                frame.actual_size,
                frame.expected_size,
                0x05,  # DATA message type (truncated frames are always DATA)
                connection_state,
            ),
        )
        error_id = cursor.lastrowid
        assert error_id is not None
        logger.debug("Logged truncated frame for session %s: %s", session_id, frame.variant)
        return error_id

    async def get_latest_sample(self, session_id: int) -> SampleRow | None:
        """Get the most recent sample for a session.

        Returns:
            SampleRow if found, None otherwise.
        """
        row = await self.db.fetchone(
            "SELECT * FROM samples WHERE session_id = ? ORDER BY captured_at DESC LIMIT 1",
            (session_id,),
        )
        return SampleRow.from_row(row) if row else None

    async def get_samples(self, session_id: int) -> list[SampleRow]:
        """Get all samples for a session, ordered by capture time.

        Args:
            session_id: Session to query.

        Returns:
            List of SampleRow ordered by captured_at ascending.
        """
        rows = await self.db.fetchall(
            "SELECT * FROM samples WHERE session_id = ? ORDER BY captured_at ASC",
            (session_id,),
        )
        return [SampleRow.from_row(r) for r in rows]

    async def get_sample_count(self, session_id: int) -> int:
        """Get the number of samples for a session."""
        row = await self.db.fetchone(
            "SELECT COUNT(*) as cnt FROM samples WHERE session_id = ?",
            (session_id,),
        )
        return row["cnt"] if row else 0

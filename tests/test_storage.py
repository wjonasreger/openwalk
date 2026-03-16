"""Tests for the OpenWalk SQLite storage layer."""

from datetime import datetime

import pytest

from openwalk.protocol.messages import DataMessage, TruncatedFrame
from openwalk.storage.database import Database
from openwalk.storage.samples import SampleManager, SampleRow
from openwalk.storage.schema import SCHEMA_VERSION
from openwalk.storage.sessions import SessionManager, SessionRow, SessionState

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db():
    """Create an in-memory database for testing."""
    async with Database(":memory:") as database:
        yield database


@pytest.fixture
async def sessions(db: Database):
    """Create a SessionManager."""
    return SessionManager(db)


@pytest.fixture
async def samples(db: Database):
    """Create a SampleManager."""
    return SampleManager(db)


def make_data_message(**overrides: object) -> DataMessage:
    """Create a DataMessage with sensible defaults."""
    defaults = {
        "timestamp": datetime(2026, 2, 17, 10, 0, 0),
        "flag": 0,
        "belt_cadence": 16,
        "distance_raw": 150,
        "belt_revs": 6,
        "steps": 42,
        "speed": 10,
        "belt_state": 1,
        "raw_hex": "5b0d0500100096000600002a0a01005d",
    }
    defaults.update(overrides)
    return DataMessage(**defaults)  # type: ignore[arg-type]


def make_truncated_frame(**overrides: object) -> TruncatedFrame:
    """Create a TruncatedFrame with sensible defaults."""
    defaults = {
        "timestamp": datetime(2026, 2, 17, 10, 0, 0),
        "expected_size": 16,
        "actual_size": 5,
        "variant": "DATA_5",
        "raw_hex": "5b0d050000",
    }
    defaults.update(overrides)
    return TruncatedFrame(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Database initialization tests
# ---------------------------------------------------------------------------


class TestDatabaseInit:
    """Test database connection, pragmas, and migration."""

    async def test_schema_version_set(self, db: Database) -> None:
        row = await db.fetchone("PRAGMA user_version")
        assert row is not None
        assert row[0] == SCHEMA_VERSION

    async def test_foreign_keys_enabled(self, db: Database) -> None:
        row = await db.fetchone("PRAGMA foreign_keys")
        assert row is not None
        assert row[0] == 1

    async def test_wal_mode_set(self, db: Database) -> None:
        """WAL mode is requested but in-memory DBs use 'memory' journal mode."""
        row = await db.fetchone("PRAGMA journal_mode")
        assert row is not None
        # In-memory databases report 'memory'; file-based would report 'wal'
        assert row[0].lower() in ("wal", "memory")

    async def test_tables_created(self, db: Database) -> None:
        rows = await db.fetchall("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        names = [r["name"] for r in rows]
        assert "sessions" in names
        assert "samples" in names
        assert "error_log" in names

    async def test_indexes_created(self, db: Database) -> None:
        rows = await db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
        )
        index_names = {r["name"] for r in rows}
        assert "idx_sessions_started_at" in index_names
        assert "idx_samples_session_id" in index_names
        assert "idx_samples_captured_at" in index_names
        assert "idx_error_log_session_id" in index_names

    async def test_migration_is_idempotent(self, db: Database) -> None:
        """Re-running connect on an already-migrated DB should not fail."""
        from openwalk.storage.schema import migrate_database

        await migrate_database(db.conn)
        row = await db.fetchone("PRAGMA user_version")
        assert row is not None
        assert row[0] == SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Session CRUD tests
# ---------------------------------------------------------------------------


class TestSessionCRUD:
    """Test session creation, retrieval, and update."""

    async def test_create_session(self, sessions: SessionManager) -> None:
        session_id = await sessions.create_session()
        assert session_id == 1

        session = await sessions.get_session(session_id)
        assert session is not None
        assert session.state == SessionState.RECORDING.value
        assert session.total_steps is None
        assert session.ended_at is None

    async def test_create_multiple_sessions(self, sessions: SessionManager) -> None:
        id1 = await sessions.create_session()
        id2 = await sessions.create_session()
        assert id1 != id2

    async def test_get_nonexistent_session(self, sessions: SessionManager) -> None:
        result = await sessions.get_session(999)
        assert result is None

    async def test_get_sessions_by_state(self, sessions: SessionManager) -> None:
        await sessions.create_session()
        await sessions.create_session()

        recording = await sessions.get_sessions_by_state(SessionState.RECORDING)
        assert len(recording) == 2

        completed = await sessions.get_sessions_by_state(SessionState.COMPLETED)
        assert len(completed) == 0

    async def test_get_recent_sessions(self, sessions: SessionManager) -> None:
        for _ in range(5):
            await sessions.create_session()

        recent = await sessions.get_recent_sessions(limit=3)
        assert len(recent) == 3

    async def test_update_totals(self, sessions: SessionManager) -> None:
        session_id = await sessions.create_session()
        await sessions.update_totals(
            session_id,
            total_steps=500,
            total_seconds=300,
            distance_raw=150,
            distance_miles=1.5,
            calories=25,
            max_speed=15,
            avg_speed=12.3,
        )

        session = await sessions.get_session(session_id)
        assert session is not None
        assert session.total_steps == 500
        assert session.total_seconds == 300
        assert session.distance_raw == 150
        assert session.distance_miles == 1.5
        assert session.calories == 25
        assert session.max_speed == 15
        assert session.avg_speed == pytest.approx(12.3)

    async def test_session_row_type(self, sessions: SessionManager) -> None:
        session_id = await sessions.create_session()
        session = await sessions.get_session(session_id)
        assert isinstance(session, SessionRow)


# ---------------------------------------------------------------------------
# Session finalization tests
# ---------------------------------------------------------------------------


class TestSessionFinalization:
    """Test session finalization from samples."""

    async def test_finalize_with_samples(
        self, sessions: SessionManager, samples: SampleManager
    ) -> None:
        session_id = await sessions.create_session()
        # Two samples to get a meaningful session delta
        msg1 = make_data_message(steps=50, distance_raw=100, speed=15, belt_state=1)
        msg2 = make_data_message(steps=150, distance_raw=350, speed=15, belt_state=1)
        await samples.insert_sample(session_id, msg1, cumulative_steps=50)
        await samples.insert_sample(session_id, msg2, cumulative_steps=150)

        # Crash recovery path: compute totals from samples then finalize
        await sessions.compute_totals_from_samples(session_id)
        await sessions.finalize_session(session_id)

        session = await sessions.get_session(session_id)
        assert session is not None
        assert session.state == SessionState.COMPLETED.value
        assert session.ended_at is not None
        assert session.total_steps == 100  # 150 - 50
        assert session.distance_raw == 250  # 350 - 100
        assert session.distance_miles == pytest.approx(2.5)
        assert session.max_speed == 15

    async def test_finalize_empty_session_deletes(self, sessions: SessionManager) -> None:
        session_id = await sessions.create_session()
        await sessions.finalize_session(session_id)

        session = await sessions.get_session(session_id)
        assert session is None  # Deleted because no samples


# ---------------------------------------------------------------------------
# Session state machine tests
# ---------------------------------------------------------------------------


class TestSessionStateMachine:
    """Test state transitions and validation."""

    async def test_recording_to_completed(
        self, sessions: SessionManager, samples: SampleManager
    ) -> None:
        session_id = await sessions.create_session()
        msg = make_data_message()
        await samples.insert_sample(session_id, msg)
        await sessions.finalize_session(session_id)

        session = await sessions.get_session(session_id)
        assert session is not None
        assert session.state == SessionState.COMPLETED.value

    async def test_completed_is_terminal(
        self, sessions: SessionManager, samples: SampleManager
    ) -> None:
        session_id = await sessions.create_session()
        await samples.insert_sample(session_id, make_data_message())
        await sessions.finalize_session(session_id)

        with pytest.raises(ValueError, match="Invalid transition"):
            await sessions.transition_state(session_id, SessionState.RECORDING)

    async def test_invalid_transition_raises(self, sessions: SessionManager) -> None:
        """RECORDING can only transition to COMPLETED via finalize."""
        session_id = await sessions.create_session()

        # Only COMPLETED is valid from RECORDING, but RECORDING is not COMPLETED
        with pytest.raises(ValueError, match="Invalid transition"):
            await sessions.transition_state(session_id, SessionState.RECORDING)

    async def test_transition_nonexistent_session(self, sessions: SessionManager) -> None:
        with pytest.raises(ValueError, match="not found"):
            await sessions.transition_state(999, SessionState.COMPLETED)


# ---------------------------------------------------------------------------
# Session recovery tests
# ---------------------------------------------------------------------------


class TestSessionRecovery:
    """Test crash recovery for interrupted sessions."""

    async def test_recover_with_samples(
        self, sessions: SessionManager, samples: SampleManager
    ) -> None:
        session_id = await sessions.create_session()
        msg1 = make_data_message(steps=25, distance_raw=100)
        msg2 = make_data_message(steps=100, distance_raw=300)
        await samples.insert_sample(session_id, msg1, cumulative_steps=25)
        await samples.insert_sample(session_id, msg2, cumulative_steps=100)

        recovered = await sessions.recover_interrupted()
        assert recovered == 1

        session = await sessions.get_session(session_id)
        assert session is not None
        assert session.state == SessionState.COMPLETED.value
        assert session.total_steps == 75  # 100 - 25

    async def test_recover_deletes_empty(self, sessions: SessionManager) -> None:
        session_id = await sessions.create_session()

        recovered = await sessions.recover_interrupted()
        assert recovered == 0

        session = await sessions.get_session(session_id)
        assert session is None

    async def test_recover_no_interrupted_sessions(self, sessions: SessionManager) -> None:
        recovered = await sessions.recover_interrupted()
        assert recovered == 0


# ---------------------------------------------------------------------------
# Sample operations tests
# ---------------------------------------------------------------------------


class TestSampleOperations:
    """Test sample insertion and queries."""

    async def test_insert_sample(self, sessions: SessionManager, samples: SampleManager) -> None:
        session_id = await sessions.create_session()
        msg = make_data_message()
        sample_id = await samples.insert_sample(session_id, msg)
        assert sample_id == 1

    async def test_insert_sample_with_cumulative(
        self, sessions: SessionManager, samples: SampleManager
    ) -> None:
        session_id = await sessions.create_session()
        msg = make_data_message(steps=42)
        await samples.insert_sample(session_id, msg, cumulative_steps=300)

        sample = await samples.get_latest_sample(session_id)
        assert sample is not None
        assert sample.steps == 300  # Cumulative, not raw 42

    async def test_insert_sample_without_cumulative(
        self, sessions: SessionManager, samples: SampleManager
    ) -> None:
        session_id = await sessions.create_session()
        msg = make_data_message(steps=42)
        await samples.insert_sample(session_id, msg)

        sample = await samples.get_latest_sample(session_id)
        assert sample is not None
        assert sample.steps == 42  # Raw value used

    async def test_get_latest_sample(
        self, sessions: SessionManager, samples: SampleManager
    ) -> None:
        session_id = await sessions.create_session()

        msg1 = make_data_message(steps=10, timestamp=datetime(2026, 2, 17, 10, 0, 0))
        msg2 = make_data_message(steps=20, timestamp=datetime(2026, 2, 17, 10, 0, 1))

        await samples.insert_sample(session_id, msg1, cumulative_steps=10)
        await samples.insert_sample(session_id, msg2, cumulative_steps=20)

        latest = await samples.get_latest_sample(session_id)
        assert latest is not None
        assert latest.steps == 20

    async def test_get_latest_sample_none(
        self, sessions: SessionManager, samples: SampleManager
    ) -> None:
        session_id = await sessions.create_session()
        result = await samples.get_latest_sample(session_id)
        assert result is None

    async def test_get_samples(self, sessions: SessionManager, samples: SampleManager) -> None:
        session_id = await sessions.create_session()

        for i in range(3):
            msg = make_data_message(steps=i * 10, timestamp=datetime(2026, 2, 17, 10, 0, i))
            await samples.insert_sample(session_id, msg, cumulative_steps=i * 10)

        all_samples = await samples.get_samples(session_id)
        assert len(all_samples) == 3
        # Verify ordering (ascending)
        assert all_samples[0].steps == 0
        assert all_samples[2].steps == 20

    async def test_get_sample_count(self, sessions: SessionManager, samples: SampleManager) -> None:
        session_id = await sessions.create_session()

        count = await samples.get_sample_count(session_id)
        assert count == 0

        await samples.insert_sample(session_id, make_data_message())
        await samples.insert_sample(session_id, make_data_message())

        count = await samples.get_sample_count(session_id)
        assert count == 2

    async def test_sample_preserves_raw_hex(
        self, sessions: SessionManager, samples: SampleManager
    ) -> None:
        session_id = await sessions.create_session()
        msg = make_data_message(raw_hex="deadbeef")
        await samples.insert_sample(session_id, msg)

        sample = await samples.get_latest_sample(session_id)
        assert sample is not None
        assert sample.raw_hex == "deadbeef"

    async def test_sample_row_type(self, sessions: SessionManager, samples: SampleManager) -> None:
        session_id = await sessions.create_session()
        await samples.insert_sample(session_id, make_data_message())

        sample = await samples.get_latest_sample(session_id)
        assert isinstance(sample, SampleRow)


# ---------------------------------------------------------------------------
# Error logging tests
# ---------------------------------------------------------------------------


class TestErrorLogging:
    """Test error_log insertion for truncated frames."""

    async def test_insert_truncated_frame(
        self, sessions: SessionManager, samples: SampleManager, db: Database
    ) -> None:
        session_id = await sessions.create_session()
        frame = make_truncated_frame()

        error_id = await samples.insert_error(session_id, frame, connection_state="CONNECTED")
        assert error_id >= 1

        row = await db.fetchone("SELECT * FROM error_log WHERE id = ?", (error_id,))
        assert row is not None
        assert row["error_type"] == "TRUNCATED_FRAME"
        assert row["raw_length"] == 5
        assert row["expected_length"] == 16
        assert row["connection_state"] == "CONNECTED"

    async def test_insert_error_without_session(self, samples: SampleManager, db: Database) -> None:
        frame = make_truncated_frame()
        error_id = await samples.insert_error(None, frame)
        assert error_id >= 1

        row = await db.fetchone("SELECT * FROM error_log WHERE id = ?", (error_id,))
        assert row is not None
        assert row["session_id"] is None

    async def test_error_message_includes_variant(
        self, sessions: SessionManager, samples: SampleManager, db: Database
    ) -> None:
        session_id = await sessions.create_session()
        frame = make_truncated_frame(variant="DATA_12", actual_size=12)
        await samples.insert_error(session_id, frame)

        row = await db.fetchone("SELECT * FROM error_log WHERE session_id = ?", (session_id,))
        assert row is not None
        assert "DATA_12" in row["error_message"]

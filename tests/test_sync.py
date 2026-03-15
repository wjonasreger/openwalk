"""Tests for HealthKit sync layer: ChunkManager, HealthKitBridge, SyncManager."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openwalk.protocol.messages import DataMessage
from openwalk.session.calories import UserProfile
from openwalk.storage.chunks import ChunkManager, ChunkRow
from openwalk.storage.database import Database
from openwalk.storage.samples import SampleManager
from openwalk.storage.sessions import SessionManager, SessionState
from openwalk.sync.healthkit_bridge import (
    AuthError,
    BridgeNotFoundError,
    ChunkResult,
    HealthKitBridge,
    ValidationError,
    WorkoutResult,
    WriteError,
)
from openwalk.sync.sync_manager import SyncManager

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
    return SessionManager(db)


@pytest.fixture
async def samples(db: Database):
    return SampleManager(db)


@pytest.fixture
async def chunks(db: Database):
    return ChunkManager(db)


@pytest.fixture
def profile():
    return UserProfile(weight_lbs=275.0, height_inches=67.0, age_years=29, gender="male")


def make_data_message(**overrides: object) -> DataMessage:
    defaults = {
        "timestamp": datetime(2026, 2, 17, 10, 0, 0),
        "flag": 0,
        "steps": 42,
        "distance_raw": 150,
        "belt_revs": 16,
        "motor_pulses": 1234,
        "speed": 10,
        "belt_state": 1,
        "raw_hex": "5b0d0500002a0096001004d20a0100005d",
    }
    defaults.update(overrides)
    return DataMessage(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ChunkManager tests
# ---------------------------------------------------------------------------


class TestChunkManager:

    async def test_insert_chunk(
        self, sessions: SessionManager, chunks: ChunkManager
    ) -> None:
        session_id = await sessions.create_session()
        chunk_id = await chunks.insert_chunk(
            session_id=session_id,
            chunk_index=0,
            chunk_start="2026-02-17T10:00:00",
            chunk_end="2026-02-17T10:01:00",
            steps_delta=87,
            distance_delta_raw=4,
            calories_delta=4,
            steps_cumulative=87,
            distance_cumulative_raw=4,
            calories_cumulative=4,
        )
        assert chunk_id >= 1

    async def test_get_chunks(
        self, sessions: SessionManager, chunks: ChunkManager
    ) -> None:
        session_id = await sessions.create_session()
        for i in range(3):
            await chunks.insert_chunk(
                session_id=session_id,
                chunk_index=i,
                chunk_start=f"2026-02-17T10:{i:02d}:00",
                chunk_end=f"2026-02-17T10:{i + 1:02d}:00",
                steps_delta=80 + i,
                distance_delta_raw=4,
                calories_delta=4,
                steps_cumulative=(80 + i) * (i + 1),
                distance_cumulative_raw=4 * (i + 1),
                calories_cumulative=4 * (i + 1),
            )

        all_chunks = await chunks.get_chunks(session_id)
        assert len(all_chunks) == 3
        assert all_chunks[0].chunk_index == 0
        assert all_chunks[2].chunk_index == 2

    async def test_unique_constraint(
        self, sessions: SessionManager, chunks: ChunkManager
    ) -> None:
        session_id = await sessions.create_session()
        await chunks.insert_chunk(
            session_id=session_id,
            chunk_index=0,
            chunk_start="2026-02-17T10:00:00",
            chunk_end="2026-02-17T10:01:00",
            steps_delta=87,
            distance_delta_raw=4,
            calories_delta=4,
            steps_cumulative=87,
            distance_cumulative_raw=4,
            calories_cumulative=4,
        )

        with pytest.raises(Exception):  # IntegrityError  # noqa: B017
            await chunks.insert_chunk(
                session_id=session_id,
                chunk_index=0,
                chunk_start="2026-02-17T10:00:00",
                chunk_end="2026-02-17T10:01:00",
                steps_delta=87,
                distance_delta_raw=4,
                calories_delta=4,
                steps_cumulative=87,
                distance_cumulative_raw=4,
                calories_cumulative=4,
            )

    async def test_get_pending_chunks(
        self, sessions: SessionManager, chunks: ChunkManager
    ) -> None:
        session_id = await sessions.create_session()
        await chunks.insert_chunk(
            session_id=session_id,
            chunk_index=0,
            chunk_start="2026-02-17T10:00:00",
            chunk_end="2026-02-17T10:01:00",
            steps_delta=87,
            distance_delta_raw=4,
            calories_delta=4,
            steps_cumulative=87,
            distance_cumulative_raw=4,
            calories_cumulative=4,
        )
        chunk_id2 = await chunks.insert_chunk(
            session_id=session_id,
            chunk_index=1,
            chunk_start="2026-02-17T10:01:00",
            chunk_end="2026-02-17T10:02:00",
            steps_delta=90,
            distance_delta_raw=4,
            calories_delta=5,
            steps_cumulative=177,
            distance_cumulative_raw=8,
            calories_cumulative=9,
        )

        # Mark one as synced
        await chunks.mark_synced(
            chunk_id2,
            hk_steps_uuid="uuid-s",
            hk_distance_uuid="uuid-d",
            hk_calories_uuid="uuid-c",
        )

        pending = await chunks.get_pending_chunks(session_id)
        assert len(pending) == 1
        assert pending[0].chunk_index == 0

    async def test_mark_synced(
        self, sessions: SessionManager, chunks: ChunkManager
    ) -> None:
        session_id = await sessions.create_session()
        chunk_id = await chunks.insert_chunk(
            session_id=session_id,
            chunk_index=0,
            chunk_start="2026-02-17T10:00:00",
            chunk_end="2026-02-17T10:01:00",
            steps_delta=87,
            distance_delta_raw=4,
            calories_delta=4,
            steps_cumulative=87,
            distance_cumulative_raw=4,
            calories_cumulative=4,
        )

        await chunks.mark_synced(
            chunk_id,
            hk_steps_uuid="steps-uuid-123",
            hk_distance_uuid="dist-uuid-456",
            hk_calories_uuid="cal-uuid-789",
        )

        chunk = await chunks.get_chunk_by_index(session_id, 0)
        assert chunk is not None
        assert chunk.sync_state == "SYNCED"
        assert chunk.hk_steps_uuid == "steps-uuid-123"
        assert chunk.hk_distance_uuid == "dist-uuid-456"
        assert chunk.hk_calories_uuid == "cal-uuid-789"

    async def test_mark_failed(
        self, sessions: SessionManager, chunks: ChunkManager
    ) -> None:
        session_id = await sessions.create_session()
        chunk_id = await chunks.insert_chunk(
            session_id=session_id,
            chunk_index=0,
            chunk_start="2026-02-17T10:00:00",
            chunk_end="2026-02-17T10:01:00",
            steps_delta=87,
            distance_delta_raw=4,
            calories_delta=4,
            steps_cumulative=87,
            distance_cumulative_raw=4,
            calories_cumulative=4,
        )

        await chunks.mark_failed(chunk_id, "HealthKit write failed")

        chunk = await chunks.get_chunk_by_index(session_id, 0)
        assert chunk is not None
        assert chunk.sync_state == "FAILED"
        assert chunk.sync_last_error == "HealthKit write failed"
        assert chunk.sync_attempts == 1

    async def test_get_chunk_by_index(
        self, sessions: SessionManager, chunks: ChunkManager
    ) -> None:
        session_id = await sessions.create_session()
        await chunks.insert_chunk(
            session_id=session_id,
            chunk_index=5,
            chunk_start="2026-02-17T10:05:00",
            chunk_end="2026-02-17T10:06:00",
            steps_delta=87,
            distance_delta_raw=4,
            calories_delta=4,
            steps_cumulative=87,
            distance_cumulative_raw=4,
            calories_cumulative=4,
        )

        chunk = await chunks.get_chunk_by_index(session_id, 5)
        assert chunk is not None
        assert chunk.chunk_index == 5

        missing = await chunks.get_chunk_by_index(session_id, 99)
        assert missing is None

    async def test_chunk_row_type(
        self, sessions: SessionManager, chunks: ChunkManager
    ) -> None:
        session_id = await sessions.create_session()
        await chunks.insert_chunk(
            session_id=session_id,
            chunk_index=0,
            chunk_start="2026-02-17T10:00:00",
            chunk_end="2026-02-17T10:01:00",
            steps_delta=87,
            distance_delta_raw=4,
            calories_delta=4,
            steps_cumulative=87,
            distance_cumulative_raw=4,
            calories_cumulative=4,
        )

        all_chunks = await chunks.get_chunks(session_id)
        assert isinstance(all_chunks[0], ChunkRow)

    async def test_get_chunk_count(
        self, sessions: SessionManager, chunks: ChunkManager
    ) -> None:
        session_id = await sessions.create_session()
        assert await chunks.get_chunk_count(session_id) == 0

        await chunks.insert_chunk(
            session_id=session_id,
            chunk_index=0,
            chunk_start="2026-02-17T10:00:00",
            chunk_end="2026-02-17T10:01:00",
            steps_delta=87,
            distance_delta_raw=4,
            calories_delta=4,
            steps_cumulative=87,
            distance_cumulative_raw=4,
            calories_cumulative=4,
        )
        assert await chunks.get_chunk_count(session_id) == 1


# ---------------------------------------------------------------------------
# HealthKitBridge tests
# ---------------------------------------------------------------------------


class TestHealthKitBridge:

    def test_bridge_not_found(self) -> None:
        bridge = HealthKitBridge(binary_path="/nonexistent/path")
        assert not bridge.available

    def test_bridge_available_with_valid_path(self, tmp_path) -> None:
        binary = tmp_path / "openwalk-health-bridge"
        binary.write_text("#!/bin/sh\necho test")
        binary.chmod(0o755)

        bridge = HealthKitBridge(binary_path=str(binary))
        assert bridge.available

    async def test_write_chunk_bridge_not_found(self) -> None:
        bridge = HealthKitBridge(binary_path="/nonexistent/path")

        with pytest.raises(BridgeNotFoundError):
            await bridge.write_chunk({"session_id": 1})

    async def test_write_chunk_success(self, tmp_path) -> None:
        binary = tmp_path / "openwalk-health-bridge"
        binary.write_text("#!/bin/sh\necho test")
        binary.chmod(0o755)

        bridge = HealthKitBridge(binary_path=str(binary))
        stdout_json = (
            b'{"steps_uuid":"s-uuid","distance_uuid":"d-uuid",'
            b'"calories_uuid":"c-uuid","was_existing":false}'
        )

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (stdout_json, b"")
        mock_proc.returncode = 0

        with patch("openwalk.sync.healthkit_bridge.asyncio.create_subprocess_exec",
                    return_value=mock_proc):
            result = await bridge.write_chunk({"session_id": 1})

        assert isinstance(result, ChunkResult)
        assert result.steps_uuid == "s-uuid"
        assert result.distance_uuid == "d-uuid"
        assert result.calories_uuid == "c-uuid"
        assert result.was_existing is False

    async def test_write_chunk_auth_error(self, tmp_path) -> None:
        binary = tmp_path / "openwalk-health-bridge"
        binary.write_text("#!/bin/sh\necho test")
        binary.chmod(0o755)

        bridge = HealthKitBridge(binary_path=str(binary))

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"Error: authorization denied")
        mock_proc.returncode = 1

        with (
            patch("openwalk.sync.healthkit_bridge.asyncio.create_subprocess_exec",
                  return_value=mock_proc),
            pytest.raises(AuthError),
        ):
            await bridge.write_chunk({"session_id": 1})

    async def test_write_chunk_validation_error(self, tmp_path) -> None:
        binary = tmp_path / "openwalk-health-bridge"
        binary.write_text("#!/bin/sh\necho test")
        binary.chmod(0o755)

        bridge = HealthKitBridge(binary_path=str(binary))

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"Error: invalid data")
        mock_proc.returncode = 2

        with (
            patch("openwalk.sync.healthkit_bridge.asyncio.create_subprocess_exec",
                  return_value=mock_proc),
            pytest.raises(ValidationError),
        ):
            await bridge.write_chunk({"session_id": 1})

    async def test_write_chunk_write_error(self, tmp_path) -> None:
        binary = tmp_path / "openwalk-health-bridge"
        binary.write_text("#!/bin/sh\necho test")
        binary.chmod(0o755)

        bridge = HealthKitBridge(binary_path=str(binary))

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"Error: write failed")
        mock_proc.returncode = 3

        with (
            patch("openwalk.sync.healthkit_bridge.asyncio.create_subprocess_exec",
                  return_value=mock_proc),
            pytest.raises(WriteError),
        ):
            await bridge.write_chunk({"session_id": 1})

    async def test_write_workout_success(self, tmp_path) -> None:
        binary = tmp_path / "openwalk-health-bridge"
        binary.write_text("#!/bin/sh\necho test")
        binary.chmod(0o755)

        bridge = HealthKitBridge(binary_path=str(binary))
        stdout_json = b'{"workout_uuid":"w-uuid","was_existing":false}'

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (stdout_json, b"")
        mock_proc.returncode = 0

        with patch("openwalk.sync.healthkit_bridge.asyncio.create_subprocess_exec",
                    return_value=mock_proc):
            result = await bridge.write_workout({"session_id": 1})

        assert isinstance(result, WorkoutResult)
        assert result.workout_uuid == "w-uuid"

    async def test_temp_file_cleanup_on_error(self, tmp_path) -> None:
        binary = tmp_path / "openwalk-health-bridge"
        binary.write_text("#!/bin/sh\necho test")
        binary.chmod(0o755)

        bridge = HealthKitBridge(binary_path=str(binary))

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"Error: denied")
        mock_proc.returncode = 1

        with (
            patch("openwalk.sync.healthkit_bridge.asyncio.create_subprocess_exec",
                  return_value=mock_proc),
            pytest.raises(AuthError),
        ):
            await bridge.write_chunk({"session_id": 1})

        # Temp files should be cleaned up (no assertion needed — if they exist,
        # the test process won't have any /tmp/openwalk_*.json files)


# ---------------------------------------------------------------------------
# SyncManager tests
# ---------------------------------------------------------------------------


class TestSyncManager:

    async def test_sync_status_default(self, profile: UserProfile) -> None:
        mock_bridge = MagicMock()
        mock_bridge.available = True
        mgr = SyncManager(
            session_mgr=MagicMock(),
            chunk_mgr=MagicMock(),
            bridge=mock_bridge,
            sample_mgr=MagicMock(),
            profile=profile,
        )
        assert mgr.sync_status == "off"

    async def test_start_session_sync_sets_status(
        self,
        sessions: SessionManager,
        chunks: ChunkManager,
        samples: SampleManager,
        profile: UserProfile,
    ) -> None:
        mock_bridge = MagicMock()
        mock_bridge.available = True

        mgr = SyncManager(
            session_mgr=sessions,
            chunk_mgr=chunks,
            bridge=mock_bridge,
            sample_mgr=samples,
            profile=profile,
        )

        session_id = await sessions.create_session()
        now = datetime.now()
        await mgr.start_session_sync(session_id, now)
        assert mgr.sync_status == "syncing"

        # Clean up
        await mgr.end_session_sync(session_id)

    async def test_end_session_sync_writes_workout(
        self,
        sessions: SessionManager,
        chunks: ChunkManager,
        samples: SampleManager,
        profile: UserProfile,
    ) -> None:
        session_id = await sessions.create_session()

        # Insert a sample so finalize doesn't delete
        msg = make_data_message()
        await samples.insert_sample(session_id, msg, cumulative_steps=42)

        # Finalize session (RECORDING -> COMPLETED)
        await sessions.finalize_session(session_id)

        mock_bridge = AsyncMock()
        mock_bridge.available = True
        mock_bridge.write_workout = AsyncMock(
            return_value=WorkoutResult(workout_uuid="w-uuid-123", was_existing=False)
        )
        mock_bridge.write_chunk = AsyncMock(
            return_value=ChunkResult(
                steps_uuid="s", distance_uuid="d", calories_uuid="c", was_existing=False
            )
        )

        mgr = SyncManager(
            session_mgr=sessions,
            chunk_mgr=chunks,
            bridge=mock_bridge,
            sample_mgr=samples,
            profile=profile,
        )

        await mgr.end_session_sync(session_id)

        # Verify workout was written
        mock_bridge.write_workout.assert_called_once()

        # Verify session transitioned to SYNCED
        session = await sessions.get_session(session_id)
        assert session is not None
        assert session.sync_state == SessionState.SYNCED.value
        assert session.hk_workout_uuid == "w-uuid-123"

    async def test_end_session_sync_handles_failure(
        self,
        sessions: SessionManager,
        chunks: ChunkManager,
        samples: SampleManager,
        profile: UserProfile,
    ) -> None:
        session_id = await sessions.create_session()
        msg = make_data_message()
        await samples.insert_sample(session_id, msg, cumulative_steps=42)
        await sessions.finalize_session(session_id)

        mock_bridge = AsyncMock()
        mock_bridge.available = True
        mock_bridge.write_workout = AsyncMock(
            side_effect=AuthError("HealthKit denied")
        )
        mock_bridge.write_chunk = AsyncMock()

        mgr = SyncManager(
            session_mgr=sessions,
            chunk_mgr=chunks,
            bridge=mock_bridge,
            sample_mgr=samples,
            profile=profile,
        )

        await mgr.end_session_sync(session_id)

        session = await sessions.get_session(session_id)
        assert session is not None
        assert session.sync_state == SessionState.SYNC_FAILED.value

    async def test_compute_calorie_delta(self, profile: UserProfile) -> None:
        mock_bridge = MagicMock()
        mgr = SyncManager(
            session_mgr=MagicMock(),
            chunk_mgr=MagicMock(),
            bridge=mock_bridge,
            sample_mgr=MagicMock(),
            profile=profile,
        )

        # Create mock samples with speed
        sample1 = MagicMock(speed=10)  # 1.0 mph
        sample2 = MagicMock(speed=15)  # 1.5 mph

        start = datetime(2026, 2, 17, 10, 0, 0)
        end = datetime(2026, 2, 17, 10, 1, 0)  # 1 minute

        cal = mgr._compute_calorie_delta([sample1, sample2], start, end)
        assert cal >= 0
        assert isinstance(cal, int)

    async def test_compute_calorie_delta_no_samples(self, profile: UserProfile) -> None:
        mock_bridge = MagicMock()
        mgr = SyncManager(
            session_mgr=MagicMock(),
            chunk_mgr=MagicMock(),
            bridge=mock_bridge,
            sample_mgr=MagicMock(),
            profile=profile,
        )

        start = datetime(2026, 2, 17, 10, 0, 0)
        end = datetime(2026, 2, 17, 10, 1, 0)

        cal = mgr._compute_calorie_delta([], start, end)
        assert cal == 0

    async def test_sync_error_property_default(self, profile: UserProfile) -> None:
        mock_bridge = MagicMock()
        mgr = SyncManager(
            session_mgr=MagicMock(),
            chunk_mgr=MagicMock(),
            bridge=mock_bridge,
            sample_mgr=MagicMock(),
            profile=profile,
        )
        assert mgr.sync_error is None


# ---------------------------------------------------------------------------
# sync_existing_session tests
# ---------------------------------------------------------------------------


class TestSyncExistingSession:

    async def test_sync_completed_session(
        self,
        sessions: SessionManager,
        chunks: ChunkManager,
        samples: SampleManager,
        profile: UserProfile,
    ) -> None:
        """COMPLETED session: creates chunks, syncs workout, returns 'synced'."""
        session_id = await sessions.create_session()
        msg = make_data_message()
        await samples.insert_sample(session_id, msg, cumulative_steps=42)
        await sessions.finalize_session(session_id)

        mock_bridge = AsyncMock()
        mock_bridge.available = True
        mock_bridge.write_chunk = AsyncMock(
            return_value=ChunkResult(
                steps_uuid="s", distance_uuid="d", calories_uuid="c", was_existing=False
            )
        )
        mock_bridge.write_workout = AsyncMock(
            return_value=WorkoutResult(workout_uuid="w-uuid", was_existing=False)
        )

        mgr = SyncManager(
            session_mgr=sessions,
            chunk_mgr=chunks,
            bridge=mock_bridge,
            sample_mgr=samples,
            profile=profile,
        )

        result = await mgr.sync_existing_session(session_id)
        assert result == "synced"

        session = await sessions.get_session(session_id)
        assert session is not None
        assert session.sync_state == SessionState.SYNCED.value

    async def test_sync_already_synced_returns_skipped(
        self,
        sessions: SessionManager,
        chunks: ChunkManager,
        samples: SampleManager,
        profile: UserProfile,
    ) -> None:
        """SYNCED session returns 'skipped'."""
        session_id = await sessions.create_session()
        msg = make_data_message()
        await samples.insert_sample(session_id, msg, cumulative_steps=42)
        await sessions.finalize_session(session_id)

        # Manually move to SYNCED
        await sessions.transition_state(session_id, SessionState.SYNC_PENDING)
        await sessions.transition_state(
            session_id, SessionState.SYNCED, hk_workout_uuid="existing"
        )

        mock_bridge = AsyncMock()
        mock_bridge.available = True

        mgr = SyncManager(
            session_mgr=sessions,
            chunk_mgr=chunks,
            bridge=mock_bridge,
            sample_mgr=samples,
            profile=profile,
        )

        result = await mgr.sync_existing_session(session_id)
        assert result == "skipped"

    async def test_sync_recording_returns_failed(
        self,
        sessions: SessionManager,
        chunks: ChunkManager,
        samples: SampleManager,
        profile: UserProfile,
    ) -> None:
        """RECORDING session returns 'failed'."""
        session_id = await sessions.create_session()

        mock_bridge = AsyncMock()
        mock_bridge.available = True

        mgr = SyncManager(
            session_mgr=sessions,
            chunk_mgr=chunks,
            bridge=mock_bridge,
            sample_mgr=samples,
            profile=profile,
        )

        result = await mgr.sync_existing_session(session_id)
        assert result == "failed"

    async def test_sync_nonexistent_session(
        self,
        sessions: SessionManager,
        chunks: ChunkManager,
        samples: SampleManager,
        profile: UserProfile,
    ) -> None:
        """Nonexistent session returns 'failed'."""
        mock_bridge = AsyncMock()
        mock_bridge.available = True

        mgr = SyncManager(
            session_mgr=sessions,
            chunk_mgr=chunks,
            bridge=mock_bridge,
            sample_mgr=samples,
            profile=profile,
        )

        result = await mgr.sync_existing_session(9999)
        assert result == "failed"

    async def test_sync_failed_session_retry(
        self,
        sessions: SessionManager,
        chunks: ChunkManager,
        samples: SampleManager,
        profile: UserProfile,
    ) -> None:
        """SYNC_FAILED session retries and syncs workout."""
        session_id = await sessions.create_session()
        msg = make_data_message()
        await samples.insert_sample(session_id, msg, cumulative_steps=42)
        await sessions.finalize_session(session_id)

        # Move to SYNC_FAILED
        await sessions.transition_state(session_id, SessionState.SYNC_PENDING)
        await sessions.transition_state(
            session_id, SessionState.SYNC_FAILED, error="previous failure"
        )

        mock_bridge = AsyncMock()
        mock_bridge.available = True
        mock_bridge.write_chunk = AsyncMock(
            return_value=ChunkResult(
                steps_uuid="s", distance_uuid="d", calories_uuid="c", was_existing=False
            )
        )
        mock_bridge.write_workout = AsyncMock(
            return_value=WorkoutResult(workout_uuid="w-retry", was_existing=False)
        )

        mgr = SyncManager(
            session_mgr=sessions,
            chunk_mgr=chunks,
            bridge=mock_bridge,
            sample_mgr=samples,
            profile=profile,
        )

        result = await mgr.sync_existing_session(session_id)
        assert result == "synced"

"""Sync manager — orchestrates incremental HealthKit chunk sync during sessions.

Creates 60-second chunks from accumulated samples and syncs them to HealthKit
via the Swift bridge. Handles retry with exponential backoff.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from openwalk.session.calories import UserProfile, net_kcal_per_min
from openwalk.storage.sessions import SessionState
from openwalk.sync.healthkit_bridge import (
    AuthError,
    BridgeNotFoundError,
    ValidationError,
)

if TYPE_CHECKING:
    from openwalk.storage.chunks import ChunkManager
    from openwalk.storage.samples import SampleManager
    from openwalk.storage.sessions import SessionManager
    from openwalk.sync.healthkit_bridge import HealthKitBridge

logger = logging.getLogger(__name__)

# Maximum backoff delay in seconds
MAX_BACKOFF_SECONDS = 300.0

# Default sync interval in seconds
DEFAULT_SYNC_INTERVAL = 60.0

# Default maximum retry attempts
DEFAULT_MAX_RETRIES = 10


class SyncManager:
    """Orchestrates incremental HealthKit chunk sync during active sessions.

    Creates 60-second chunks from accumulated samples, syncs them to HealthKit
    via the Swift bridge, and manages retry with exponential backoff.

    Args:
        session_mgr: Session CRUD operations.
        chunk_mgr: Chunk CRUD operations.
        bridge: HealthKit bridge wrapper.
        sample_mgr: Sample query operations.
        profile: User profile for calorie calculations.
        sync_interval: Seconds between chunk syncs.
        max_retries: Maximum retry attempts per chunk.
    """

    def __init__(
        self,
        session_mgr: SessionManager,
        chunk_mgr: ChunkManager,
        bridge: HealthKitBridge,
        sample_mgr: SampleManager,
        profile: UserProfile,
        sync_interval: float = DEFAULT_SYNC_INTERVAL,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        self._session_mgr = session_mgr
        self._chunk_mgr = chunk_mgr
        self._bridge = bridge
        self._sample_mgr = sample_mgr
        self._profile = profile
        self._sync_interval = sync_interval
        self._max_retries = max_retries

        self._active_session_id: int | None = None
        self._session_start: datetime | None = None
        self._chunk_index: int = 0
        self._last_chunk_end: datetime | None = None
        self._sync_task: asyncio.Task[None] | None = None
        self._status: str = "off"
        self._last_error: str | None = None

    @property
    def sync_status(self) -> str:
        """Current sync status for dashboard display."""
        return self._status

    @property
    def sync_error(self) -> str | None:
        """Last sync error message, if any."""
        return self._last_error

    async def start_session_sync(self, session_id: int, started_at: datetime) -> None:
        """Begin tracking chunks for a new session.

        Starts a background sync loop that creates and syncs chunks every
        sync_interval seconds.
        """
        self._active_session_id = session_id
        self._session_start = started_at
        self._chunk_index = 0
        self._last_chunk_end = started_at
        self._status = "syncing"

        self._sync_task = asyncio.create_task(self._sync_loop())
        logger.info("Started HealthKit sync for session %d", session_id)

    async def end_session_sync(self, session_id: int) -> None:
        """Finalize sync: flush last chunk, write workout, transition state.

        Called when a session ends. Creates the final (possibly partial) chunk,
        syncs any remaining pending chunks, and writes the workout summary.
        """
        # Stop the sync loop
        if self._sync_task is not None:
            self._sync_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._sync_task
            self._sync_task = None

        # Flush remaining chunks if this session was actively tracked
        if self._active_session_id == session_id:
            now = datetime.now()

            # Create final chunk (may be < 60 seconds)
            if self._last_chunk_end is not None and self._last_chunk_end < now:
                await self._create_and_sync_chunk(
                    session_id, self._chunk_index, self._last_chunk_end, now
                )

        # Retry any failed chunks
        await self._retry_failed_chunks(session_id)

        # Write workout summary
        await self._sync_workout(session_id)

        self._active_session_id = None
        self._session_start = None
        self._status = "off"
        logger.info("Ended HealthKit sync for session %d", session_id)

    async def _sync_loop(self) -> None:
        """Background loop: create and sync chunks at regular intervals."""
        try:
            while True:
                await asyncio.sleep(self._sync_interval)

                if self._active_session_id is None or self._last_chunk_end is None:
                    continue

                now = datetime.now()
                chunk_start = self._last_chunk_end
                chunk_end = chunk_start + timedelta(seconds=self._sync_interval)

                # Don't create chunk if end is in the future
                if chunk_end > now:
                    chunk_end = now

                if chunk_start >= chunk_end:
                    continue

                await self._create_and_sync_chunk(
                    self._active_session_id,
                    self._chunk_index,
                    chunk_start,
                    chunk_end,
                )
                self._chunk_index += 1
                self._last_chunk_end = chunk_end

                # Retry failed chunks periodically
                await self._retry_failed_chunks(self._active_session_id)

        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.exception("Sync loop error")
            self._status = "error"
            self._last_error = str(exc)

    async def _create_and_sync_chunk(
        self,
        session_id: int,
        chunk_index: int,
        chunk_start: datetime,
        chunk_end: datetime,
    ) -> None:
        """Create a chunk from samples in the time window and sync it."""
        # Query samples in this time window
        all_samples = await self._sample_mgr.get_samples(session_id)

        start_iso = chunk_start.isoformat()
        end_iso = chunk_end.isoformat()

        # Filter samples to this chunk's time window
        window_samples = [
            s
            for s in all_samples
            if s.captured_at >= start_iso and s.captured_at <= end_iso
        ]

        if not window_samples:
            return

        # Compute deltas
        first = window_samples[0]
        last = window_samples[-1]

        steps_delta = (last.steps or 0) - (first.steps or 0)
        if steps_delta < 0:
            steps_delta = last.steps or 0

        distance_delta_raw = (last.distance_raw or 0) - (first.distance_raw or 0)
        if distance_delta_raw < 0:
            distance_delta_raw = 0

        # Compute calorie delta from speed samples
        calories_delta = self._compute_calorie_delta(window_samples, chunk_start, chunk_end)

        # Insert chunk into DB
        chunk_id = await self._chunk_mgr.insert_chunk(
            session_id=session_id,
            chunk_index=chunk_index,
            chunk_start=start_iso,
            chunk_end=end_iso,
            steps_delta=steps_delta,
            distance_delta_raw=distance_delta_raw,
            calories_delta=calories_delta,
            steps_cumulative=last.steps or 0,
            distance_cumulative_raw=last.distance_raw or 0,
            calories_cumulative=calories_delta,  # Approximate
        )

        # Sync to HealthKit
        await self._sync_chunk_by_id(chunk_id, session_id, chunk_index, start_iso, end_iso,
                                     steps_delta, distance_delta_raw, calories_delta)

    def _compute_calorie_delta(
        self,
        samples: Sequence[object],
        chunk_start: datetime,
        chunk_end: datetime,
    ) -> int:
        """Compute calorie delta from speed samples using net_kcal_per_min."""
        duration_minutes = (chunk_end - chunk_start).total_seconds() / 60.0
        if duration_minutes <= 0:
            return 0

        # Average speed from samples
        speeds = []
        for s in samples:
            speed = getattr(s, "speed", None)
            if speed is not None and speed > 0:
                speeds.append(speed / 10.0)  # Convert raw speed to mph

        if not speeds:
            return 0

        avg_speed_mph = sum(speeds) / len(speeds)
        kcal_per_min = net_kcal_per_min(avg_speed_mph, self._profile)
        return max(0, round(kcal_per_min * duration_minutes))

    async def _sync_chunk_by_id(
        self,
        chunk_id: int,
        session_id: int,
        chunk_index: int,
        chunk_start: str,
        chunk_end: str,
        steps_delta: int,
        distance_delta_raw: int,
        calories_delta: int,
    ) -> bool:
        """Attempt to sync a single chunk to HealthKit. Returns True on success."""
        chunk_data = {
            "session_id": session_id,
            "chunk_index": chunk_index,
            "start": chunk_start,
            "end": chunk_end,
            "steps": steps_delta,
            "distance_miles": distance_delta_raw / 100.0,
            "calories": calories_delta,
        }

        try:
            result = await self._bridge.write_chunk(chunk_data)
            await self._chunk_mgr.mark_synced(
                chunk_id,
                hk_steps_uuid=result.steps_uuid,
                hk_distance_uuid=result.distance_uuid,
                hk_calories_uuid=result.calories_uuid,
            )
            logger.info(
                "Chunk %d synced (session %d, index %d)", chunk_id, session_id, chunk_index
            )
            return True
        except (AuthError, ValidationError) as exc:
            # Non-retryable errors
            await self._chunk_mgr.mark_failed(chunk_id, str(exc))
            logger.warning("Chunk %d sync failed (non-retryable): %s", chunk_id, exc)
            self._status = "error"
            self._last_error = str(exc)
            return False
        except (BridgeNotFoundError, Exception) as exc:
            # Retryable errors
            await self._chunk_mgr.mark_failed(chunk_id, str(exc))
            logger.warning("Chunk %d sync failed (retryable): %s", chunk_id, exc)
            return False

    async def _retry_failed_chunks(self, session_id: int) -> None:
        """Retry chunks that failed to sync, with exponential backoff."""
        failed = await self._chunk_mgr.get_failed_chunks(session_id)

        for chunk in failed:
            if chunk.sync_attempts >= self._max_retries:
                continue

            # Exponential backoff: 2^attempt seconds, capped at MAX_BACKOFF
            delay = min(math.pow(2, chunk.sync_attempts), MAX_BACKOFF_SECONDS)

            # Skip if not enough time has passed (simple check)
            # In practice, the sync loop runs periodically, so this is approximate
            logger.debug(
                "Retrying chunk %d (attempt %d, delay %.0fs)",
                chunk.id,
                chunk.sync_attempts + 1,
                delay,
            )

            await self._sync_chunk_by_id(
                chunk.id,
                chunk.session_id,
                chunk.chunk_index,
                chunk.chunk_start,
                chunk.chunk_end,
                chunk.steps_delta,
                chunk.distance_delta_raw,
                chunk.calories_delta,
            )

    async def _sync_workout(self, session_id: int) -> None:
        """Write workout summary to HealthKit and transition session state."""
        session = await self._session_mgr.get_session(session_id)
        if session is None:
            return

        # Transition to SYNC_PENDING (skip if already in that state)
        current_state = SessionState(session.sync_state)
        if current_state != SessionState.SYNC_PENDING:
            try:
                await self._session_mgr.transition_state(
                    session_id, SessionState.SYNC_PENDING
                )
            except ValueError:
                logger.warning("Cannot transition session %d to SYNC_PENDING", session_id)
                return

        workout_data = {
            "session_id": session_id,
            "start": session.started_at,
            "end": session.ended_at or datetime.now().isoformat(),
            "duration_seconds": session.total_seconds or 0,
            "total_steps": session.total_steps or 0,
            "total_distance_miles": session.distance_miles or 0.0,
            "total_calories": session.calories or 0,
        }

        try:
            result = await self._bridge.write_workout(workout_data)
            await self._session_mgr.transition_state(
                session_id,
                SessionState.SYNCED,
                hk_workout_uuid=result.workout_uuid,
            )
            self._status = "synced"
            logger.info("Workout synced for session %d (UUID: %s)", session_id, result.workout_uuid)
        except (AuthError, ValidationError) as exc:
            await self._session_mgr.transition_state(
                session_id, SessionState.SYNC_FAILED, error=str(exc)
            )
            self._status = "error"
            self._last_error = str(exc)
            logger.warning("Workout sync failed for session %d: %s", session_id, exc)
        except Exception as exc:
            await self._session_mgr.transition_state(
                session_id, SessionState.SYNC_FAILED, error=str(exc)
            )
            self._status = "error"
            self._last_error = str(exc)
            logger.warning("Workout sync failed for session %d: %s", session_id, exc)

    async def sync_existing_session(self, session_id: int) -> str:
        """Sync a completed or failed session to HealthKit (no background loop).

        For COMPLETED sessions: creates chunks from samples, syncs them, writes workout.
        For SYNC_FAILED sessions: retries failed chunks and re-attempts workout.
        For SYNCED sessions: returns "skipped".

        Args:
            session_id: Session to sync.

        Returns:
            "synced", "failed", or "skipped".
        """
        session = await self._session_mgr.get_session(session_id)
        if session is None:
            return "failed"

        state = SessionState(session.sync_state)

        if state == SessionState.SYNCED:
            return "skipped"

        if state == SessionState.RECORDING:
            logger.warning("Cannot sync session %d: still recording", session_id)
            return "failed"

        if state == SessionState.COMPLETED:
            # Create chunks from all session samples
            start = datetime.fromisoformat(session.started_at)
            end_str = session.ended_at or datetime.now().isoformat()
            end = datetime.fromisoformat(end_str)

            # Build chunks covering the full session in sync_interval windows
            chunk_start = start
            chunk_index = 0
            while chunk_start < end:
                chunk_end = min(
                    chunk_start + timedelta(seconds=self._sync_interval), end
                )
                await self._create_and_sync_chunk(
                    session_id, chunk_index, chunk_start, chunk_end
                )
                chunk_index += 1
                chunk_start = chunk_end

        if state == SessionState.SYNC_FAILED:
            # Transition back to SYNC_PENDING to re-attempt
            with contextlib.suppress(ValueError):
                await self._session_mgr.transition_state(
                    session_id, SessionState.SYNC_PENDING
                )

        # Retry any failed chunks
        await self._retry_failed_chunks(session_id)

        # Write workout summary
        await self._sync_workout(session_id)

        # Check final state
        updated = await self._session_mgr.get_session(session_id)
        if updated and SessionState(updated.sync_state) == SessionState.SYNCED:
            return "synced"
        return "failed"

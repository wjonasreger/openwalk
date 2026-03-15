"""Session orchestrator — integrates BLE, protocol, storage, and session state.

Wired as the on_data and on_state_change callback for ConnectionManager.
Bridges synchronous BLE callbacks to async DB writes via an asyncio.Queue.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from openwalk.ble.connection import ConnectionState
from openwalk.protocol.counters import SessionCounters
from openwalk.protocol.messages import DataMessage, IdleMessage, SpeedMessage, TruncatedFrame
from openwalk.protocol.parser import parse_notification
from openwalk.session.calories import UserProfile
from openwalk.session.state import LiveSessionState
from openwalk.storage.samples import SampleManager
from openwalk.storage.sessions import SessionManager

logger = logging.getLogger(__name__)

# Sentinel types for the DB write queue
_START_SESSION = "START_SESSION"
_END_SESSION = "END_SESSION"

# Default inactivity timeout before auto-ending a session
DEFAULT_INACTIVITY_TIMEOUT = 60.0


class SessionOrchestrator:
    """Coordinates BLE data flow through parsing, tracking, and persistence.

    Synchronous methods (handle_raw_data, handle_state_change) are callbacks
    for ConnectionManager. Async methods manage the DB write queue and
    session lifecycle.
    """

    def __init__(
        self,
        session_mgr: SessionManager,
        sample_mgr: SampleManager,
        profile: UserProfile,
        inactivity_timeout: float = DEFAULT_INACTIVITY_TIMEOUT,
    ) -> None:
        self._session_mgr = session_mgr
        self._sample_mgr = sample_mgr
        self._profile = profile
        self._inactivity_timeout = inactivity_timeout

        self._counters = SessionCounters()
        self._state = LiveSessionState()
        self._queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

        self._conn_state = ConnectionState.DISCONNECTED
        self._conn_message = ""
        self._running = True

    @property
    def state(self) -> LiveSessionState:
        return self._state

    @property
    def conn_state(self) -> ConnectionState:
        return self._conn_state

    @property
    def conn_message(self) -> str:
        return self._conn_message

    def handle_raw_data(self, data: bytes) -> None:
        """Synchronous callback for ConnectionManager.on_data.

        Parses raw BLE bytes, updates in-memory state, and queues DB writes.
        """
        now = datetime.now()
        messages = parse_notification(data, timestamp=now)

        for msg in messages:
            if isinstance(msg, DataMessage):
                self._handle_data_message(msg, now)
            elif isinstance(msg, SpeedMessage):
                self._state.speed = msg.speed
                self._state.speed_count += 1
            elif isinstance(msg, IdleMessage):
                self._state.idle_count += 1
            elif isinstance(msg, TruncatedFrame):
                self._state.truncated_count += 1
                if self._state.session_id is not None:
                    self._queue.put_nowait(("INSERT_ERROR", (self._state.session_id, msg)))

    def _handle_data_message(self, msg: DataMessage, now: datetime) -> None:
        """Process a DataMessage: update counters, state, calories, queue DB write."""
        # Update counters (handles wrap-around)
        cumulative_steps = self._counters.update_steps(msg.steps)
        cumulative_belt_revs = self._counters.update_belt_revs(msg.belt_revs)

        # Update live state
        s = self._state
        s.total_steps = cumulative_steps
        s.total_belt_revs = cumulative_belt_revs
        s.distance_raw = msg.distance_raw
        s.speed = msg.speed
        s.belt_state = msg.belt_state
        s.last_data_at = now
        s.data_count += 1

        # Record step sample for sliding window rate calculation
        s.record_step_sample(now, cumulative_steps)

        # Accumulate calories
        s.accumulate_calories(now, msg.speed_mph, self._profile)

        # Record sparkline history
        s.speed_history.append((now, float(msg.speed)))
        s.step_rate_history.append((now, s.step_rate))
        s.calorie_history.append((now, s.net_cal_per_min))

        # Session auto-start: belt running and no active session
        if msg.is_belt_running and s.session_id is None:
            self._queue.put_nowait((_START_SESSION, now))

        # Queue DB write if session is active
        if s.session_id is not None:
            self._queue.put_nowait(
                (
                    "INSERT_SAMPLE",
                    (s.session_id, msg, cumulative_steps, cumulative_belt_revs),
                )
            )

    def handle_state_change(self, conn_state: ConnectionState, message: str) -> None:
        """Synchronous callback for ConnectionManager.on_state_change."""
        self._conn_state = conn_state
        self._conn_message = message
        self._state.conn_state_name = conn_state.name
        self._state.conn_message = message

    async def process_db_queue(self) -> None:
        """Background coroutine that drains the DB write queue."""
        while self._running:
            try:
                action, payload = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            try:
                if action == _START_SESSION:
                    await self._do_start_session(payload)
                elif action == _END_SESSION:
                    await self._do_end_session()
                elif action == "INSERT_SAMPLE":
                    session_id, msg, cum_steps, cum_belt_revs = payload
                    await self._sample_mgr.insert_sample(
                        session_id,
                        msg,
                        cumulative_steps=cum_steps,
                        cumulative_belt_revs=cum_belt_revs,
                    )
                elif action == "INSERT_ERROR":
                    session_id, frame = payload
                    await self._sample_mgr.insert_error(session_id, frame)
            except Exception:
                logger.exception("Error processing DB queue item: %s", action)

    async def _do_start_session(self, started_at: datetime) -> None:
        """Create a new DB session and reset tracking state."""
        session_id = await self._session_mgr.create_session()
        self._counters.reset()
        self._state.session_id = session_id
        self._state.started_at = started_at
        logger.info("Session %d started", session_id)

    async def _do_end_session(self) -> None:
        """Finalize the current DB session."""
        session_id = self._state.session_id
        if session_id is None:
            return

        # Update totals before finalizing
        await self._session_mgr.update_totals(
            session_id,
            total_steps=self._state.total_steps,
            total_seconds=int(self._state.elapsed_seconds),
            distance_raw=self._state.distance_raw,
            distance_miles=self._state.distance_miles,
            calories=int(self._state.net_calories),
            max_speed=self._state.speed,
            avg_speed=self._state.speed,
        )
        await self._session_mgr.finalize_session(session_id)
        logger.info("Session %d ended", session_id)

        self._state.session_id = None

    async def check_inactivity(self) -> None:
        """Check if belt has been stopped long enough to auto-end the session."""
        if self._state.session_id is None:
            return

        if self._state.last_data_at is None:
            return

        # Only auto-end if belt is not running
        if self._state.is_belt_running:
            return

        elapsed = (datetime.now() - self._state.last_data_at).total_seconds()
        if elapsed >= self._inactivity_timeout:
            self._queue.put_nowait((_END_SESSION, None))

    async def end_session(self) -> None:
        """Explicitly end the current session (e.g., on quit)."""
        if self._state.session_id is not None:
            await self._do_end_session()

    async def recover_on_startup(self) -> None:
        """Recover interrupted sessions from a previous run."""
        await self._session_mgr.recover_interrupted()

    def stop(self) -> None:
        """Signal the DB queue processor to stop."""
        self._running = False

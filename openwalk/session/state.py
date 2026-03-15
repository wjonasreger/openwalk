"""Live session state — mutable in-memory container for real-time metrics."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from openwalk.session.calories import UserProfile, gross_kcal_per_min, net_kcal_per_min

# Sliding window for step rate calculation
STEP_RATE_WINDOW_SECONDS = 10
STEP_RATE_MIN_WINDOW = 3  # seconds


@dataclass
class LiveSessionState:
    """In-memory state for the currently active session.

    Updated by the SessionOrchestrator, read by the dashboard renderer.
    """

    # Session identity
    session_id: int | None = None
    started_at: datetime | None = None

    # Cumulative metrics
    total_steps: int = 0
    total_belt_revs: int = 0
    distance_raw: int = 0

    # Current readings
    speed: int = 0
    belt_state: int = 0
    last_data_at: datetime | None = None

    # Calorie accumulation
    gross_calories: float = 0.0
    net_calories: float = 0.0
    last_cal_timestamp: datetime | None = None

    # Message counters
    data_count: int = 0
    speed_count: int = 0
    idle_count: int = 0
    truncated_count: int = 0

    # Sparkline history: (timestamp, value) tuples
    speed_history: deque[tuple[datetime, float]] = field(default_factory=lambda: deque(maxlen=7200))
    step_rate_history: deque[tuple[datetime, float]] = field(
        default_factory=lambda: deque(maxlen=7200)
    )
    calorie_history: deque[tuple[datetime, float]] = field(
        default_factory=lambda: deque(maxlen=7200)
    )

    # Step rate sliding window: (timestamp, cumulative_steps)
    _step_window: deque[tuple[datetime, int]] = field(default_factory=lambda: deque(maxlen=500))

    # Connection state (stored by orchestrator)
    conn_state_name: str = "DISCONNECTED"
    conn_message: str = ""

    @property
    def elapsed_seconds(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.last_data_at or datetime.now()
        return (end - self.started_at).total_seconds()

    @property
    def elapsed_formatted(self) -> str:
        total = int(self.elapsed_seconds)
        hours = total // 3600
        minutes = (total % 3600) // 60
        seconds = total % 60
        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    @property
    def distance_miles(self) -> float:
        return self.distance_raw / 100.0

    @property
    def speed_mph(self) -> float:
        return self.speed / 10.0

    @property
    def is_belt_running(self) -> bool:
        return self.belt_state == 1

    @property
    def step_rate(self) -> float:
        """Steps per minute over the last 10-second sliding window."""
        if len(self._step_window) < 2:
            return 0.0

        oldest_time, oldest_steps = self._step_window[0]
        newest_time, newest_steps = self._step_window[-1]
        window_seconds = (newest_time - oldest_time).total_seconds()

        if window_seconds < STEP_RATE_MIN_WINDOW:
            return 0.0

        delta_steps = newest_steps - oldest_steps
        return (delta_steps / window_seconds) * 60

    @property
    def gross_cal_per_min(self) -> float:
        return self._current_gross_rate

    @property
    def net_cal_per_min(self) -> float:
        return self._current_net_rate

    _current_gross_rate: float = field(default=0.0, repr=False)
    _current_net_rate: float = field(default=0.0, repr=False)

    def record_step_sample(self, timestamp: datetime, cumulative_steps: int) -> None:
        """Record a step sample for the sliding window step rate calculation."""
        window_start = timestamp - timedelta(seconds=STEP_RATE_WINDOW_SECONDS)
        # Remove old entries
        while self._step_window and self._step_window[0][0] < window_start:
            self._step_window.popleft()
        self._step_window.append((timestamp, cumulative_steps))

    def accumulate_calories(
        self, timestamp: datetime, speed_mph: float, profile: UserProfile
    ) -> None:
        """Accumulate calories based on time delta since last calculation."""
        gross_rate = gross_kcal_per_min(speed_mph, profile)
        net_rate = net_kcal_per_min(speed_mph, profile)
        self._current_gross_rate = gross_rate
        self._current_net_rate = net_rate

        if self.last_cal_timestamp is not None:
            delta_minutes = (timestamp - self.last_cal_timestamp).total_seconds() / 60.0
            if delta_minutes > 0:
                self.gross_calories += gross_rate * delta_minutes
                self.net_calories += net_rate * delta_minutes

        self.last_cal_timestamp = timestamp

    def reset(self) -> None:
        """Reset all state for a new session."""
        self.session_id = None
        self.started_at = None
        self.total_steps = 0
        self.total_belt_revs = 0
        self.distance_raw = 0
        self.speed = 0
        self.belt_state = 0
        self.last_data_at = None
        self.gross_calories = 0.0
        self.net_calories = 0.0
        self.last_cal_timestamp = None
        self.data_count = 0
        self.speed_count = 0
        self.idle_count = 0
        self.truncated_count = 0
        self.speed_history.clear()
        self.step_rate_history.clear()
        self.calorie_history.clear()
        self._step_window.clear()
        self._current_gross_rate = 0.0
        self._current_net_rate = 0.0

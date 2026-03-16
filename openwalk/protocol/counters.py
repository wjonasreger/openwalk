"""Counter tracking with wrap-around detection for BLE protocol fields.

The treadmill uses:
- uint16 counter for steps (bytes 10-11 big-endian, actual footsteps)
- uint8 counter for belt revolutions (byte 8)

These counters wrap at their max values during long sessions.
This module tracks cumulative totals across wrap-arounds.

Wrap detection uses a threshold to prevent false positives:
- If current < previous AND previous > threshold, a wrap occurred
"""

from openwalk.ble.characteristics import (
    UINT8_MAX,
    UINT16_MAX,
    WRAP_THRESHOLD_UINT8,
    WRAP_THRESHOLD_UINT16,
)


class CounterTracker:
    """Track a counter that wraps at a configurable max value.

    Used for:
    - Step counter (bytes 10-11 of DATA message, uint16 BE, actual footsteps)
    - Belt revolution counter (byte 8 of DATA message, uint8)

    Example:
        >>> tracker = CounterTracker()
        >>> tracker.update(10)
        10
        >>> tracker.update(20)
        20
        >>> tracker.update(254)
        254
        >>> tracker.update(255)
        255
        >>> tracker.update(0)  # Wrap detected!
        256
        >>> tracker.update(5)
        261
    """

    def __init__(
        self, max_value: int = UINT8_MAX, wrap_threshold: int = WRAP_THRESHOLD_UINT8
    ) -> None:
        """Initialize counter tracker.

        Args:
            max_value: Maximum counter value before wrap (255 for uint8, 65535 for uint16).
            wrap_threshold: Threshold for wrap detection.
        """
        self.total: int = 0
        self.previous_raw: int | None = None
        self.wrap_count: int = 0
        self._max_value = max_value
        self._wrap_threshold = wrap_threshold

    def update(self, raw_value: int) -> int:
        """Update with new raw value and return cumulative total.

        Args:
            raw_value: Current raw counter value

        Returns:
            Cumulative total accounting for wrap-arounds
        """
        if self.previous_raw is None:
            # First value - initialize
            self.previous_raw = raw_value
            self.total = raw_value
            return self.total

        # Detect wrap: current < previous AND previous > threshold
        if raw_value < self.previous_raw and self.previous_raw > self._wrap_threshold:
            self.wrap_count += 1

        # Calculate cumulative total
        self.total = (self.wrap_count * (self._max_value + 1)) + raw_value
        self.previous_raw = raw_value

        return self.total

    def reset(self) -> None:
        """Reset the tracker for a new session."""
        self.total = 0
        self.previous_raw = None
        self.wrap_count = 0

    @property
    def has_wrapped(self) -> bool:
        """Check if the counter has wrapped at least once."""
        return self.wrap_count > 0


class SessionCounters:
    """Track all counters for a walking session.

    Manages step counter (uint16) and belt revolution counter (uint8),
    providing a unified interface for session tracking.

    Example:
        >>> counters = SessionCounters()
        >>> counters.update_steps(10)
        10
        >>> counters.update_belt_revs(4)
        4
        >>> counters.total_steps
        10
        >>> counters.total_belt_revs
        4
    """

    def __init__(self) -> None:
        """Initialize session counters."""
        self.steps = CounterTracker(
            max_value=UINT16_MAX, wrap_threshold=WRAP_THRESHOLD_UINT16
        )
        self.belt_revs = CounterTracker(
            max_value=UINT8_MAX, wrap_threshold=WRAP_THRESHOLD_UINT8
        )

    def update_steps(self, raw_steps: int) -> int:
        """Update step counter and return cumulative total.

        Args:
            raw_steps: Current raw step count from DATA message (bytes 10-11 BE)

        Returns:
            Cumulative total steps
        """
        return self.steps.update(raw_steps)

    def update_belt_revs(self, raw_revs: int) -> int:
        """Update belt revolution counter and return cumulative total.

        Args:
            raw_revs: Current raw belt revolutions from DATA message (byte 8)

        Returns:
            Cumulative total belt revolutions
        """
        return self.belt_revs.update(raw_revs)

    def reset(self) -> None:
        """Reset all counters for a new session."""
        self.steps.reset()
        self.belt_revs.reset()

    @property
    def total_steps(self) -> int:
        """Get cumulative total steps."""
        return self.steps.total

    @property
    def total_belt_revs(self) -> int:
        """Get cumulative total belt revolutions."""
        return self.belt_revs.total


def calculate_delta(previous: int, current: int, max_value: int = UINT8_MAX) -> int:
    """Calculate delta between two counter values, handling wrap-around.

    Args:
        previous: Previous counter value
        current: Current counter value
        max_value: Maximum value before wrap (default 255)

    Returns:
        Delta between values, accounting for wrap
    """
    if current >= previous:
        return current - previous
    else:
        # Wrap occurred: count from previous to max, then 0 to current
        return (max_value - previous) + current + 1

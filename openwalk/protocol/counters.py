"""Counter tracking with wrap-around detection for uint8 fields.

The treadmill uses uint8 counters for steps and belt revolutions.
These counters wrap from 255 back to 0 during long sessions.
This module tracks cumulative totals across wrap-arounds.

Wrap detection uses a threshold of 200 to prevent false positives:
- If current < previous AND previous > 200, a wrap occurred
- This avoids false positives from small backward jumps due to data artifacts
"""

from openwalk.ble.characteristics import UINT8_MAX, WRAP_THRESHOLD


class CounterTracker:
    """Track a uint8 counter that wraps at 255.

    Used for:
    - Step counter (byte 4 of DATA message)
    - Belt revolution counter (byte 8 of DATA message)

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

    def __init__(self) -> None:
        """Initialize counter tracker."""
        self.total: int = 0
        self.previous_raw: int | None = None
        self.wrap_count: int = 0

    def update(self, raw_value: int) -> int:
        """Update with new raw value and return cumulative total.

        Args:
            raw_value: Current raw counter value (0-255)

        Returns:
            Cumulative total accounting for wrap-arounds
        """
        if self.previous_raw is None:
            # First value - initialize
            self.previous_raw = raw_value
            self.total = raw_value
            return self.total

        # Detect wrap: current < previous AND previous > threshold
        if raw_value < self.previous_raw and self.previous_raw > WRAP_THRESHOLD:
            self.wrap_count += 1

        # Calculate cumulative total
        self.total = (self.wrap_count * (UINT8_MAX + 1)) + raw_value
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

    Manages step counter and belt revolution counter together,
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
        >>> counters.steps_per_belt_rev
        2.5
    """

    def __init__(self) -> None:
        """Initialize session counters."""
        self.steps = CounterTracker()
        self.belt_revs = CounterTracker()

    def update_steps(self, raw_steps: int) -> int:
        """Update step counter and return cumulative total.

        Args:
            raw_steps: Current raw step count from DATA message (byte 4)

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

    @property
    def steps_per_belt_rev(self) -> float:
        """Calculate steps per belt revolution.

        Expected ratio is approximately 2.55 steps/revolution
        based on belt circumference and stride length.

        Returns:
            Steps per revolution, or 0.0 if no revolutions recorded
        """
        if self.belt_revs.total == 0:
            return 0.0
        return self.steps.total / self.belt_revs.total


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

"""BLE notification handling and message routing.

Routes raw BLE notification bytes through the protocol parser
and dispatches typed messages to registered callbacks.
"""

import logging
from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta

from openwalk.protocol.messages import AnyFrame
from openwalk.protocol.parser import parse_notification

logger = logging.getLogger(__name__)

MessageCallback = Callable[[AnyFrame], None]


class MessageRateTracker:
    """Track message rate over a sliding window."""

    def __init__(self, window_seconds: float = 10.0) -> None:
        self.window = timedelta(seconds=window_seconds)
        self._timestamps: deque[datetime] = deque()

    def record(self) -> None:
        """Record that a message was received."""
        now = datetime.now()
        self._timestamps.append(now)

        cutoff = now - self.window
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()

    @property
    def rate(self) -> float:
        """Current messages per second (average over window)."""
        if len(self._timestamps) < 2:
            return 0.0

        duration = (self._timestamps[-1] - self._timestamps[0]).total_seconds()
        if duration == 0:
            return 0.0

        return (len(self._timestamps) - 1) / duration

    @property
    def count(self) -> int:
        """Message count in current window."""
        return len(self._timestamps)

    def reset(self) -> None:
        """Clear all tracked timestamps."""
        self._timestamps.clear()


class NotificationRouter:
    """Routes BLE notifications through the parser to message callbacks.

    Catches exceptions from the parser and callbacks to prevent
    notification handler crashes from killing the BLE connection.
    """

    def __init__(self, on_message: MessageCallback | None = None) -> None:
        self._on_message = on_message
        self.rate_tracker = MessageRateTracker()
        self.total_notifications = 0
        self.total_messages = 0
        self.parse_errors = 0

    def handle_notification(self, sender: int, data: bytes) -> None:
        """Handle a raw BLE notification.

        This is the callback passed to BleakClient.start_notify().

        Args:
            sender: Characteristic handle.
            data: Raw notification bytes.
        """
        self.total_notifications += 1

        try:
            messages = parse_notification(data)
        except Exception:
            self.parse_errors += 1
            logger.exception("Parse error on notification %d", self.total_notifications)
            return

        for msg in messages:
            self.total_messages += 1
            self.rate_tracker.record()

            if self._on_message:
                try:
                    self._on_message(msg)
                except Exception:
                    logger.exception("Error in message callback")

    def set_callback(self, on_message: MessageCallback) -> None:
        """Set or replace the message callback."""
        self._on_message = on_message

"""Tests for BLE connection manager components."""

import json
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from openwalk.ble.connection import (
    ConnectionState,
    ConnectionWatchdog,
    DisconnectTolerance,
    ReconnectStrategy,
)
from openwalk.ble.notifications import MessageRateTracker, NotificationRouter
from openwalk.ble.scanner import CACHE_FILE, load_device_uuid, save_device_uuid

# =============================================================================
# ReconnectStrategy
# =============================================================================


class TestReconnectStrategy:
    def test_initial_delay(self) -> None:
        strategy = ReconnectStrategy(initial_delay=2.0)
        assert strategy.next_delay() == 2.0

    def test_exponential_backoff_schedule(self) -> None:
        strategy = ReconnectStrategy(initial_delay=2.0, multiplier=1.5, max_delay=60.0)
        delays = [strategy.next_delay() for _ in range(5)]
        assert delays[0] == 2.0
        assert delays[1] == pytest.approx(3.0)
        assert delays[2] == pytest.approx(4.5)
        assert delays[3] == pytest.approx(6.75)
        assert delays[4] == pytest.approx(10.125)

    def test_max_delay_cap(self) -> None:
        strategy = ReconnectStrategy(initial_delay=2.0, multiplier=1.5, max_delay=60.0)
        # Exhaust backoff until cap
        for _ in range(50):
            delay = strategy.next_delay()
        assert delay == 60.0

    def test_attempt_counter(self) -> None:
        strategy = ReconnectStrategy()
        assert strategy.attempt_count == 0
        strategy.next_delay()
        assert strategy.attempt_count == 1
        strategy.next_delay()
        assert strategy.attempt_count == 2

    def test_reset(self) -> None:
        strategy = ReconnectStrategy(initial_delay=2.0, multiplier=1.5)
        strategy.next_delay()
        strategy.next_delay()
        assert strategy.attempt_count == 2

        strategy.reset()
        assert strategy.attempt_count == 0
        assert strategy.next_delay() == 2.0

    def test_should_retry_infinite(self) -> None:
        strategy = ReconnectStrategy(max_attempts=0)
        for _ in range(100):
            strategy.next_delay()
        assert strategy.should_retry() is True

    def test_should_retry_limited(self) -> None:
        strategy = ReconnectStrategy(max_attempts=3)
        assert strategy.should_retry() is True
        strategy.next_delay()
        strategy.next_delay()
        strategy.next_delay()
        assert strategy.should_retry() is False

    def test_should_retry_resets(self) -> None:
        strategy = ReconnectStrategy(max_attempts=2)
        strategy.next_delay()
        strategy.next_delay()
        assert strategy.should_retry() is False

        strategy.reset()
        assert strategy.should_retry() is True


# =============================================================================
# ConnectionWatchdog
# =============================================================================


class TestConnectionWatchdog:
    def test_not_stale_before_start(self) -> None:
        watchdog = ConnectionWatchdog(timeout_seconds=1.0)
        assert watchdog.is_stale() is False

    def test_not_stale_after_start(self) -> None:
        watchdog = ConnectionWatchdog(timeout_seconds=1.0)
        watchdog.start()
        assert watchdog.is_stale() is False

    def test_stale_after_timeout(self) -> None:
        watchdog = ConnectionWatchdog(timeout_seconds=0.1)
        watchdog.start()
        time.sleep(0.15)
        assert watchdog.is_stale() is True

    def test_reset_prevents_stale(self) -> None:
        watchdog = ConnectionWatchdog(timeout_seconds=0.2)
        watchdog.start()
        time.sleep(0.1)
        watchdog.reset()
        time.sleep(0.1)
        assert watchdog.is_stale() is False

    def test_stop(self) -> None:
        watchdog = ConnectionWatchdog(timeout_seconds=0.05)
        watchdog.start()
        time.sleep(0.1)
        watchdog.stop()
        assert watchdog.is_stale() is False


# =============================================================================
# DisconnectTolerance
# =============================================================================


class TestDisconnectTolerance:
    def test_brief_disconnect(self) -> None:
        tolerance = DisconnectTolerance(tolerance_seconds=5.0)
        tolerance.on_disconnect()
        # Reconnect immediately (< 5s)
        was_brief = tolerance.on_reconnect()
        assert was_brief is True
        assert tolerance.brief_disconnect_count == 1

    def test_long_disconnect(self) -> None:
        tolerance = DisconnectTolerance(tolerance_seconds=0.05)
        tolerance.on_disconnect()
        time.sleep(0.1)
        was_brief = tolerance.on_reconnect()
        assert was_brief is False
        assert tolerance.brief_disconnect_count == 0

    def test_no_prior_disconnect(self) -> None:
        tolerance = DisconnectTolerance()
        was_brief = tolerance.on_reconnect()
        assert was_brief is False

    def test_total_disconnect_count(self) -> None:
        tolerance = DisconnectTolerance(tolerance_seconds=5.0)
        tolerance.on_disconnect()
        tolerance.on_reconnect()
        tolerance.on_disconnect()
        tolerance.on_reconnect()
        assert tolerance.total_disconnect_count == 2

    def test_reset(self) -> None:
        tolerance = DisconnectTolerance(tolerance_seconds=5.0)
        tolerance.on_disconnect()
        tolerance.on_reconnect()
        tolerance.reset()
        assert tolerance.brief_disconnect_count == 0
        assert tolerance.total_disconnect_count == 0


# =============================================================================
# ConnectionState
# =============================================================================


class TestConnectionState:
    def test_all_states_exist(self) -> None:
        states = [s.value for s in ConnectionState]
        assert "disconnected" in states
        assert "scanning" in states
        assert "connecting" in states
        assert "connected" in states
        assert "subscribed" in states
        assert "error" in states

    def test_state_values(self) -> None:
        assert ConnectionState.DISCONNECTED.value == "disconnected"
        assert ConnectionState.SUBSCRIBED.value == "subscribed"
        assert ConnectionState.ERROR.value == "error"


# =============================================================================
# MessageRateTracker
# =============================================================================


class TestMessageRateTracker:
    def test_initial_rate_zero(self) -> None:
        tracker = MessageRateTracker()
        assert tracker.rate == 0.0
        assert tracker.count == 0

    def test_count_increments(self) -> None:
        tracker = MessageRateTracker()
        tracker.record()
        tracker.record()
        tracker.record()
        assert tracker.count == 3

    def test_rate_calculation(self) -> None:
        tracker = MessageRateTracker(window_seconds=10.0)
        # Record messages with known timing
        for _ in range(5):
            tracker.record()
            time.sleep(0.05)
        # Rate should be approximately 1/0.05 = 20 msg/sec
        # But we have 5 messages over ~0.2s, so (5-1)/0.2 = 20
        assert tracker.rate > 10.0  # Reasonable lower bound

    def test_window_expiration(self) -> None:
        tracker = MessageRateTracker(window_seconds=0.1)
        tracker.record()
        tracker.record()
        time.sleep(0.15)
        tracker.record()  # This triggers cleanup
        assert tracker.count == 1  # Old ones expired

    def test_reset(self) -> None:
        tracker = MessageRateTracker()
        tracker.record()
        tracker.record()
        tracker.reset()
        assert tracker.count == 0
        assert tracker.rate == 0.0


# =============================================================================
# NotificationRouter
# =============================================================================


class TestNotificationRouter:
    def _make_idle_frame(self) -> bytes:
        """Create a valid IDLE frame (7 bytes)."""
        return bytes([0x5B, 0x04, 0x03, 0x01, 0x01, 0x00, 0x5D])

    def _make_speed_frame(self) -> bytes:
        """Create a valid SPEED frame (5 bytes)."""
        return bytes([0x5B, 0x02, 0x11, 0x0A, 0x5D])

    def _make_data_frame(self) -> bytes:
        """Create a valid DATA frame (16 bytes)."""
        return bytes(
            [
                0x5B,
                0x0D,
                0x05,
                0x00,  # start, length, type, flag
                0x0A,  # steps=10
                0x00,  # reserved
                0x64,
                0x00,  # distance=100 (1.00 mi)
                0x04,  # belt_revs=4
                0x00,  # reserved
                0x20,
                0x00,  # motor_pulses=32
                0x0A,  # speed=10
                0x01,  # belt_state=1 (running)
                0x00,  # padding
                0x5D,  # end
            ]
        )

    def test_callback_receives_messages(self) -> None:
        messages: list = []
        router = NotificationRouter(on_message=lambda msg: messages.append(msg))

        router.handle_notification(0, self._make_idle_frame())
        assert len(messages) == 1

    def test_multiple_messages_in_notification(self) -> None:
        messages: list = []
        router = NotificationRouter(on_message=lambda msg: messages.append(msg))

        # Concatenated SPEED + IDLE
        data = self._make_speed_frame() + self._make_idle_frame()
        router.handle_notification(0, data)
        assert len(messages) == 2

    def test_counts_tracked(self) -> None:
        router = NotificationRouter()
        router.handle_notification(0, self._make_data_frame())
        router.handle_notification(0, self._make_idle_frame())
        assert router.total_notifications == 2
        assert router.total_messages == 2

    def test_parse_error_does_not_crash(self) -> None:
        router = NotificationRouter()
        # Invalid data should not raise
        router.handle_notification(0, b"\x00\x01\x02")
        assert router.total_notifications == 1

    def test_callback_error_does_not_crash(self) -> None:
        def bad_callback(msg: object) -> None:
            raise ValueError("callback exploded")

        router = NotificationRouter(on_message=bad_callback)
        # Should not raise despite callback error
        router.handle_notification(0, self._make_idle_frame())
        assert router.total_messages == 1

    def test_rate_tracking(self) -> None:
        router = NotificationRouter()
        router.handle_notification(0, self._make_data_frame())
        router.handle_notification(0, self._make_data_frame())
        assert router.rate_tracker.count == 2

    def test_set_callback(self) -> None:
        messages: list = []
        router = NotificationRouter()
        router.handle_notification(0, self._make_idle_frame())
        assert len(messages) == 0

        router.set_callback(lambda msg: messages.append(msg))
        router.handle_notification(0, self._make_idle_frame())
        assert len(messages) == 1


# =============================================================================
# Scanner UUID Caching
# =============================================================================


class TestDeviceCache:
    def test_save_and_load(self, tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
        import openwalk.ble.scanner as scanner_mod

        cache_file = tmp_path / "device_cache.json"  # type: ignore[operator]
        monkeypatch.setattr(scanner_mod, "CACHE_FILE", cache_file)

        save_device_uuid("BM70_DT", "ABC-123")
        result = load_device_uuid("BM70_DT")
        assert result == "ABC-123"

    def test_load_missing_file(self, tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
        import openwalk.ble.scanner as scanner_mod

        cache_file = tmp_path / "nonexistent" / "cache.json"  # type: ignore[operator]
        monkeypatch.setattr(scanner_mod, "CACHE_FILE", cache_file)

        result = load_device_uuid("BM70_DT")
        assert result is None

    def test_load_missing_device(self, tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
        import openwalk.ble.scanner as scanner_mod

        cache_file = tmp_path / "device_cache.json"  # type: ignore[operator]
        monkeypatch.setattr(scanner_mod, "CACHE_FILE", cache_file)

        save_device_uuid("OTHER_DEVICE", "XYZ-789")
        result = load_device_uuid("BM70_DT")
        assert result is None

    def test_corrupt_cache_handled(self, tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
        import openwalk.ble.scanner as scanner_mod

        cache_file = tmp_path / "device_cache.json"  # type: ignore[operator]
        monkeypatch.setattr(scanner_mod, "CACHE_FILE", cache_file)

        cache_file.write_text("not valid json{{{")
        result = load_device_uuid("BM70_DT")
        assert result is None

    def test_overwrite_existing(self, tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
        import openwalk.ble.scanner as scanner_mod

        cache_file = tmp_path / "device_cache.json"  # type: ignore[operator]
        monkeypatch.setattr(scanner_mod, "CACHE_FILE", cache_file)

        save_device_uuid("BM70_DT", "OLD-UUID")
        save_device_uuid("BM70_DT", "NEW-UUID")
        assert load_device_uuid("BM70_DT") == "NEW-UUID"

    def test_multiple_devices(self, tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
        import openwalk.ble.scanner as scanner_mod

        cache_file = tmp_path / "device_cache.json"  # type: ignore[operator]
        monkeypatch.setattr(scanner_mod, "CACHE_FILE", cache_file)

        save_device_uuid("BM70_DT", "UUID-1")
        save_device_uuid("OTHER", "UUID-2")
        assert load_device_uuid("BM70_DT") == "UUID-1"
        assert load_device_uuid("OTHER") == "UUID-2"

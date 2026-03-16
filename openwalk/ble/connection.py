"""BLE connection manager for InMovement Unsit treadmill.

Provides a resilient connection abstraction with automatic reconnection,
connection state machine, stale connection watchdog, and state event emission.
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from enum import Enum

from bleak import BleakClient
from bleak.exc import BleakDeviceNotFoundError, BleakError

from openwalk.ble.characteristics import DEVICE_NAME, NOTIFY_CHAR_UUID
from openwalk.ble.notifications import NotificationRouter
from openwalk.ble.scanner import discover_or_use_cached, save_device_uuid

logger = logging.getLogger(__name__)


class ConnectionState(Enum):
    """Connection states for the BLE connection manager."""

    DISCONNECTED = "disconnected"
    SCANNING = "scanning"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    SUBSCRIBED = "subscribed"
    ERROR = "error"


StateChangeCallback = Callable[[ConnectionState, str], None]
DataCallback = Callable[[bytes], None]


class ReconnectStrategy:
    """Exponential backoff reconnection strategy.

    Backoff schedule (default): 2s, 3s, 4.5s, 6.75s, ... capped at 60s.
    """

    def __init__(
        self,
        initial_delay: float = 2.0,
        multiplier: float = 1.5,
        max_delay: float = 60.0,
        max_attempts: int = 0,
    ) -> None:
        self.initial_delay = initial_delay
        self.multiplier = multiplier
        self.max_delay = max_delay
        self.max_attempts = max_attempts
        self.attempt_count = 0
        self._current_delay = initial_delay

    def next_delay(self) -> float:
        """Get next reconnection delay and increment attempt counter.

        Returns:
            Delay in seconds before next reconnection attempt.
        """
        self.attempt_count += 1
        delay = self._current_delay
        self._current_delay = min(self._current_delay * self.multiplier, self.max_delay)
        return delay

    def reset(self) -> None:
        """Reset backoff state after successful connection."""
        self.attempt_count = 0
        self._current_delay = self.initial_delay

    def should_retry(self) -> bool:
        """Check if another reconnection attempt should be made."""
        if self.max_attempts == 0:
            return True
        return self.attempt_count < self.max_attempts


class ConnectionWatchdog:
    """Detect stale connections where BLE reports connected but no data flows.

    The treadmill sends IDLE heartbeats ~1/sec even when the belt is stopped,
    so 30s of silence indicates a stale connection.
    """

    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self.timeout = timedelta(seconds=timeout_seconds)
        self._last_data_time: datetime | None = None
        self._started = False

    def start(self) -> None:
        """Start the watchdog timer."""
        self._last_data_time = datetime.now()
        self._started = True

    def reset(self) -> None:
        """Reset the watchdog timer (call on every notification received)."""
        self._last_data_time = datetime.now()

    def is_stale(self) -> bool:
        """Check if the connection is stale (no data for > timeout)."""
        if not self._started or self._last_data_time is None:
            return False
        return (datetime.now() - self._last_data_time) > self.timeout

    def stop(self) -> None:
        """Stop the watchdog."""
        self._started = False
        self._last_data_time = None


class DisconnectTolerance:
    """Track brief disconnects to distinguish transient drops from real disconnects.

    Brief disconnects (<5s) are expected during early connection instability
    and should not end an active session.
    """

    def __init__(self, tolerance_seconds: float = 5.0) -> None:
        self.tolerance = timedelta(seconds=tolerance_seconds)
        self._disconnect_time: datetime | None = None
        self.brief_disconnect_count = 0
        self.total_disconnect_count = 0

    def on_disconnect(self) -> None:
        """Record disconnect timestamp."""
        self._disconnect_time = datetime.now()
        self.total_disconnect_count += 1

    def on_reconnect(self) -> bool:
        """Check if reconnection was within the tolerance window.

        Returns:
            True if this was a brief disconnect (< tolerance).
        """
        if self._disconnect_time is None:
            return False

        duration = datetime.now() - self._disconnect_time
        was_brief = duration < self.tolerance
        if was_brief:
            self.brief_disconnect_count += 1

        self._disconnect_time = None
        return was_brief

    def reset(self) -> None:
        """Reset disconnect tracking."""
        self._disconnect_time = None
        self.brief_disconnect_count = 0
        self.total_disconnect_count = 0


class ConnectionManager:
    """Manages the BLE connection lifecycle to the treadmill.

    Handles device discovery, connection establishment, notification subscription,
    automatic reconnection with exponential backoff, and stale connection detection.

    Usage::

        async def on_data(data: bytes):
            messages = parse_notification(data)
            for msg in messages:
                process(msg)

        def on_state(state: ConnectionState, message: str):
            print(f"[{state.value}] {message}")

        manager = ConnectionManager(on_data=on_data, on_state_change=on_state)
        await manager.start()  # Blocks until stop() is called
    """

    def __init__(
        self,
        device_name: str = DEVICE_NAME,
        on_data: DataCallback | None = None,
        on_state_change: StateChangeCallback | None = None,
        scan_timeout: float = 20.0,
        connect_timeout: float = 10.0,
        watchdog_timeout: float = 30.0,
    ) -> None:
        self.device_name = device_name
        self._on_data = on_data
        self._on_state_change = on_state_change
        self._scan_timeout = scan_timeout
        self._connect_timeout = connect_timeout

        self._client: BleakClient | None = None
        self._state = ConnectionState.DISCONNECTED
        self._running = False
        self._task: asyncio.Task[None] | None = None

        self.reconnect = ReconnectStrategy()
        self.watchdog = ConnectionWatchdog(timeout_seconds=watchdog_timeout)
        self.disconnect_tolerance = DisconnectTolerance()
        self.router = NotificationRouter()

    @property
    def state(self) -> ConnectionState:
        """Current connection state."""
        return self._state

    @property
    def is_connected(self) -> bool:
        """Whether the connection is active and subscribed."""
        return self._state == ConnectionState.SUBSCRIBED

    def _set_state(self, state: ConnectionState, message: str = "") -> None:
        """Update connection state and notify listeners."""
        old_state = self._state
        self._state = state

        if old_state != state:
            logger.info("State: %s -> %s (%s)", old_state.value, state.value, message)

        if self._on_state_change:
            try:
                self._on_state_change(state, message)
            except Exception:
                logger.exception("Error in state change callback")

    def _notification_handler(self, sender: object, data: bytearray) -> None:
        """Handle BLE notification: reset watchdog and route data."""
        self.watchdog.reset()
        logger.debug("Notification: %d bytes, hex=%s", len(data), bytes(data).hex())

        if self._on_data:
            try:
                self._on_data(bytes(data))
            except Exception:
                logger.exception("Error in data callback")

        self.router.handle_notification(0, bytes(data))

    async def start(self) -> None:
        """Start the connection manager.

        This runs the connection loop until stop() is called.
        Automatically discovers, connects, subscribes, and reconnects.
        """
        if self._running:
            logger.warning("Connection manager already running")
            return

        self._running = True
        logger.info("Connection manager starting for %s", self.device_name)

        try:
            await self._connection_loop()
        finally:
            self._running = False
            await self._disconnect()
            self._set_state(ConnectionState.DISCONNECTED, "Stopped")

    async def start_background(self) -> None:
        """Start the connection manager as a background task."""
        self._task = asyncio.create_task(self.start())

    async def stop(self) -> None:
        """Stop the connection manager gracefully."""
        logger.info("Connection manager stopping")
        self._running = False

        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

        await self._disconnect()

    async def _disconnect(self) -> None:
        """Disconnect from the BLE device."""
        if self._client and self._client.is_connected:
            with contextlib.suppress(Exception):
                await self._client.stop_notify(NOTIFY_CHAR_UUID)
            with contextlib.suppress(Exception):
                await self._client.disconnect()
        self._client = None
        self.watchdog.stop()

    async def _connection_loop(self) -> None:
        """Main connection loop: discover, connect, monitor, reconnect."""
        while self._running:
            try:
                # Phase 1: Discover device
                self._set_state(ConnectionState.SCANNING, f"Searching for {self.device_name}...")
                device_address = await discover_or_use_cached(
                    self.device_name, timeout=self._scan_timeout
                )

                if not device_address:
                    if not self.reconnect.should_retry():
                        self._set_state(ConnectionState.ERROR, "Device not found after max retries")
                        return
                    delay = self.reconnect.next_delay()
                    self._set_state(
                        ConnectionState.DISCONNECTED,
                        f"Device not found. Retrying in {delay:.1f}s",
                    )
                    await asyncio.sleep(delay)
                    continue

                # Phase 2: Connect
                self._set_state(
                    ConnectionState.CONNECTING,
                    f"Attempt #{self.reconnect.attempt_count + 1}",
                )
                self._client = BleakClient(
                    device_address,
                    timeout=self._connect_timeout,
                    disconnected_callback=self._on_bleak_disconnect,
                )
                await self._client.connect()

                if not self._client.is_connected:
                    raise BleakError("Client reports not connected after connect()")

                self._set_state(ConnectionState.CONNECTED, "Subscribing to notifications...")

                # Phase 3: Subscribe to notifications
                await self._client.start_notify(NOTIFY_CHAR_UUID, self._notification_handler)

                # Connection successful
                self.reconnect.reset()
                was_brief = self.disconnect_tolerance.on_reconnect()
                if was_brief:
                    logger.info("Brief disconnect recovered (< 5s)")

                # Cache the UUID for faster future reconnects
                save_device_uuid(self.device_name, device_address)

                self.watchdog.start()
                self._set_state(ConnectionState.SUBSCRIBED, "Ready")

                # Phase 4: Monitor connection
                await self._monitor_connection()

            except asyncio.CancelledError:
                return

            except (TimeoutError, BleakDeviceNotFoundError, BleakError, OSError) as e:
                logger.warning("Connection error: %s", e)
                await self._disconnect()
                self.disconnect_tolerance.on_disconnect()

                if not self.reconnect.should_retry():
                    self._set_state(ConnectionState.ERROR, f"Max retries exceeded: {e}")
                    return

                delay = self.reconnect.next_delay()
                self._set_state(
                    ConnectionState.DISCONNECTED,
                    f"Error: {e}. Retrying in {delay:.1f}s",
                )
                await asyncio.sleep(delay)

    async def _monitor_connection(self) -> None:
        """Monitor an active connection for disconnect or stale state."""
        while self._running and self._client and self._client.is_connected:
            await asyncio.sleep(1.0)

            if self.watchdog.is_stale():
                timeout_secs = self.watchdog.timeout.total_seconds()
                logger.warning("Connection stale (no data for %.0fs)", timeout_secs)
                self._set_state(ConnectionState.DISCONNECTED, "Connection stale - no data received")
                await self._disconnect()
                self.disconnect_tolerance.on_disconnect()
                return

        # Connection lost (detected by bleak or client.is_connected check)
        if self._running:
            logger.info("Connection lost")
            self._set_state(ConnectionState.DISCONNECTED, "Connection lost")
            self.disconnect_tolerance.on_disconnect()
            await self._disconnect()

    def _on_bleak_disconnect(self, client: BleakClient) -> None:
        """Bleak disconnected callback (called from bleak's event loop)."""
        logger.info("Bleak reported disconnect")

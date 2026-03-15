"""BLE connection management for InMovement Unsit treadmill."""

from openwalk.ble.characteristics import (
    # GATT Services
    DEVICE_INFO_SERVICE_UUID,
    # Device Discovery
    DEVICE_NAME,
    # Frame Markers
    FRAME_END,
    FRAME_START,
    # Message Sizes
    MSG_SIZE_DATA,
    MSG_SIZE_IDLE,
    MSG_SIZE_SPEED,
    # Message Types
    MSG_TYPE_DATA,
    MSG_TYPE_IDLE,
    MSG_TYPE_SPEED,
    # Characteristics
    NOTIFY_CHAR_UUID,
    SECONDARY_NOTIFY_CHAR_UUID,
    SERVICE_UUID,
    # Field Constants
    SPEED_MAX,
    SPEED_MIN,
    UINT8_MAX,
    WRAP_THRESHOLD,
    WRITE_CHAR_UUID,
)
from openwalk.ble.connection import (
    ConnectionManager,
    ConnectionState,
    ConnectionWatchdog,
    DisconnectTolerance,
    ReconnectStrategy,
)
from openwalk.ble.notifications import (
    MessageRateTracker,
    NotificationRouter,
)
from openwalk.ble.scanner import (
    discover_or_use_cached,
    find_all_treadmills,
    find_treadmill,
    load_device_uuid,
    save_device_uuid,
)

__all__ = [
    # GATT Services
    "DEVICE_INFO_SERVICE_UUID",
    "SERVICE_UUID",
    # Characteristics
    "NOTIFY_CHAR_UUID",
    "SECONDARY_NOTIFY_CHAR_UUID",
    "WRITE_CHAR_UUID",
    # Device Discovery
    "DEVICE_NAME",
    # Message Types
    "MSG_TYPE_DATA",
    "MSG_TYPE_IDLE",
    "MSG_TYPE_SPEED",
    # Message Sizes
    "MSG_SIZE_DATA",
    "MSG_SIZE_IDLE",
    "MSG_SIZE_SPEED",
    # Frame Markers
    "FRAME_END",
    "FRAME_START",
    # Field Constants
    "SPEED_MAX",
    "SPEED_MIN",
    "UINT8_MAX",
    "WRAP_THRESHOLD",
    # Connection Manager
    "ConnectionManager",
    "ConnectionState",
    "ConnectionWatchdog",
    "DisconnectTolerance",
    "ReconnectStrategy",
    # Notifications
    "MessageRateTracker",
    "NotificationRouter",
    # Scanner
    "discover_or_use_cached",
    "find_all_treadmills",
    "find_treadmill",
    "load_device_uuid",
    "save_device_uuid",
]

"""BLE connection management for InMovement Unsit treadmill."""

from openwalk.ble.characteristics import (
    # GATT Services
    DEVICE_INFO_SERVICE_UUID,
    SERVICE_UUID,
    # Characteristics
    NOTIFY_CHAR_UUID,
    SECONDARY_NOTIFY_CHAR_UUID,
    WRITE_CHAR_UUID,
    # Device Discovery
    DEVICE_NAME,
    # Message Types
    MSG_TYPE_DATA,
    MSG_TYPE_IDLE,
    MSG_TYPE_SPEED,
    # Message Sizes
    MSG_SIZE_DATA,
    MSG_SIZE_IDLE,
    MSG_SIZE_SPEED,
    # Frame Markers
    FRAME_END,
    FRAME_START,
    # Field Constants
    SPEED_MAX,
    SPEED_MIN,
    UINT8_MAX,
    WRAP_THRESHOLD,
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
]

"""BLE service and characteristic UUIDs for InMovement Unsit treadmill.

The treadmill uses a Microchip BM70 BLE module with ISSC Transparent UART protocol.
This is NOT the standard FTMS (Fitness Machine Service) protocol.
"""

# =============================================================================
# GATT Services
# =============================================================================

# ISSC Transparent UART Service (Primary data service)
SERVICE_UUID = "49535343-fe7d-4ae5-8fa9-9fafd205e455"

# Device Information Service (standard BLE)
DEVICE_INFO_SERVICE_UUID = "0000180a-0000-1000-8000-00805f9b34fb"

# =============================================================================
# ISSC Transparent UART Characteristics
# =============================================================================

# Primary RX/TX - subscribe for telemetry notifications
NOTIFY_CHAR_UUID = "49535343-1e4d-4bd9-ba61-23c647249616"

# Write characteristic - send commands to treadmill
WRITE_CHAR_UUID = "49535343-8841-43f4-a8d4-ecbe34729bb3"

# Secondary notify (no activity observed during testing)
SECONDARY_NOTIFY_CHAR_UUID = "49535343-4c8a-39b3-2f49-511cff073b7e"

# =============================================================================
# Device Discovery
# =============================================================================

# Advertisement name for BM70 module
DEVICE_NAME = "BM70_DT"

# =============================================================================
# Message Type Codes
# =============================================================================

# IDLE message - sent when belt is stopped (~1/sec heartbeat)
MSG_TYPE_IDLE = 0x03

# DATA message - primary telemetry with steps, distance, speed, etc.
MSG_TYPE_DATA = 0x05

# SPEED message - speed change notification
MSG_TYPE_SPEED = 0x11

# =============================================================================
# Expected Message Sizes (total bytes including frame markers)
# =============================================================================

MSG_SIZE_IDLE = 7  # [5B] [04] [03] [b3] [b4] [b5] [5D]
MSG_SIZE_SPEED = 5  # [5B] [02] [11] [speed] [5D]
MSG_SIZE_DATA = 16  # [5B] [0D] [05] ... 13 bytes payload ... [5D]

# =============================================================================
# Frame Markers
# =============================================================================

FRAME_START = 0x5B  # ASCII '['
FRAME_END = 0x5D  # ASCII ']'

# =============================================================================
# DATA Message Byte Positions
# =============================================================================

# Byte positions within a 16-byte DATA frame
DATA_BYTE_START = 0  # 0x5B
DATA_BYTE_LENGTH = 1  # 0x0D (13)
DATA_BYTE_TYPE = 2  # 0x05
DATA_BYTE_FLAG = 3  # 0-4, cycles during session
DATA_BYTE_STEPS = 4  # uint8, wraps at 255
DATA_BYTE_RESERVED1 = 5  # always 0x00
DATA_BYTE_DIST_LO = 6  # uint16 LE low byte
DATA_BYTE_DIST_HI = 7  # uint16 LE high byte
DATA_BYTE_BELT_REVS = 8  # uint8, wraps at 255
DATA_BYTE_RESERVED2 = 9  # always 0x00
DATA_BYTE_MOTOR_LO = 10  # uint16 LE low byte
DATA_BYTE_MOTOR_HI = 11  # uint16 LE high byte
DATA_BYTE_SPEED = 12  # 1-20 setting
DATA_BYTE_BELT_STATE = 13  # 1 = running
DATA_BYTE_PADDING = 14  # always 0x00
DATA_BYTE_END = 15  # 0x5D

# =============================================================================
# Field Ranges and Limits
# =============================================================================

SPEED_MIN = 1
SPEED_MAX = 20

# Wrap-around detection threshold for uint8 counters
# If current < previous AND previous > this threshold, wrap occurred
WRAP_THRESHOLD = 200

# Maximum value for uint8 counter before wrap
UINT8_MAX = 255

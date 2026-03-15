"""Frame validation for InMovement Unsit treadmill BLE protocol.

Validation is performed in strict order:
1. Frame structure (markers, minimum length)
2. Length byte matches actual size
3. Message type is valid
4. Size matches type
5. Field constraints (ranges, reserved bytes)
"""

from openwalk.ble.characteristics import (
    FRAME_END,
    FRAME_START,
    MSG_SIZE_DATA,
    MSG_SIZE_IDLE,
    MSG_SIZE_SPEED,
    MSG_TYPE_DATA,
    MSG_TYPE_IDLE,
    MSG_TYPE_SPEED,
    SPEED_MAX,
    SPEED_MIN,
)

# Mapping of message types to expected sizes
EXPECTED_SIZES: dict[int, int] = {
    MSG_TYPE_IDLE: MSG_SIZE_IDLE,
    MSG_TYPE_DATA: MSG_SIZE_DATA,
    MSG_TYPE_SPEED: MSG_SIZE_SPEED,
}


def is_valid_frame(frame: bytes) -> bool:
    """Check if a frame has valid structure.

    Validates:
    - Minimum length of 4 bytes
    - Starts with 0x5B
    - Ends with 0x5D
    - Length byte matches actual payload size

    Args:
        frame: Raw frame bytes

    Returns:
        True if frame structure is valid
    """
    if len(frame) < 4:
        return False

    if frame[0] != FRAME_START:
        return False

    if frame[-1] != FRAME_END:
        return False

    # Length byte should equal payload size (total - 3 for start, length, end)
    length_byte = frame[1]
    actual_payload = len(frame) - 3

    return length_byte == actual_payload


def is_truncated_data(frame: bytes) -> bool:
    """Check if a frame is a truncated DATA message.

    Truncated DATA frames have:
    - Type byte = 0x05 (DATA)
    - But total size < 16 bytes

    These occur when BLE notifications are cut off mid-transmission.
    Expected rate: ~0.7% of messages.

    Args:
        frame: Raw frame bytes

    Returns:
        True if this is a truncated DATA frame
    """
    if len(frame) < 3:
        return False

    type_byte = frame[2]

    # DATA type but wrong size = truncated
    return type_byte == MSG_TYPE_DATA and len(frame) != MSG_SIZE_DATA


def get_truncation_variant(frame: bytes) -> str:
    """Get the truncation variant name for a truncated DATA frame.

    Observed variants:
    - DATA_5: 5 bytes (header only)
    - DATA_9: 9 bytes (header + steps + partial distance)
    - DATA_12: 12 bytes (header through partial motor_pulses)

    Args:
        frame: Truncated frame bytes

    Returns:
        Variant name like "DATA_5"
    """
    return f"DATA_{len(frame)}"


def validate_frame_type(frame: bytes) -> tuple[bool, str]:
    """Validate that frame type is known and size matches.

    Args:
        frame: Raw frame bytes

    Returns:
        Tuple of (is_valid, error_message)
    """
    if len(frame) < 3:
        return False, "Frame too short to have type byte"

    type_byte = frame[2]
    actual_size = len(frame)

    if type_byte not in EXPECTED_SIZES:
        return False, f"Unknown message type: 0x{type_byte:02X}"

    expected_size = EXPECTED_SIZES[type_byte]
    if actual_size != expected_size:
        return False, f"Size mismatch: expected {expected_size}, got {actual_size}"

    return True, ""


def validate_data_fields(frame: bytes) -> tuple[bool, str]:
    """Validate DATA message field constraints.

    Checks:
    - Reserved bytes (5, 9, 14) are 0x00
    - Flag (byte 3) is 0-4
    - Speed (byte 12) is 0-30 (allowing margin beyond 1-20)
    - Belt state (byte 13) is 0 or 1

    Args:
        frame: 16-byte DATA frame

    Returns:
        Tuple of (is_valid, error_message)
    """
    if len(frame) != MSG_SIZE_DATA:
        return False, f"DATA frame must be 16 bytes, got {len(frame)}"

    # Check reserved bytes
    if frame[5] != 0x00:
        return False, f"Reserved byte 5 is 0x{frame[5]:02X}, expected 0x00"

    if frame[9] != 0x00:
        return False, f"Reserved byte 9 is 0x{frame[9]:02X}, expected 0x00"

    if frame[14] != 0x00:
        return False, f"Reserved byte 14 is 0x{frame[14]:02X}, expected 0x00"

    # Check flag range (allowing some margin)
    flag = frame[3]
    if flag > 10:
        return False, f"Flag value {flag} is outside expected range 0-4"

    # Check speed range (allowing margin)
    speed = frame[12]
    if speed > 30:
        return False, f"Speed value {speed} is outside expected range 0-20"

    # Check belt state
    belt_state = frame[13]
    if belt_state not in (0, 1):
        return False, f"Belt state {belt_state} is not 0 or 1"

    return True, ""


def validate_speed_fields(frame: bytes) -> tuple[bool, str]:
    """Validate SPEED message field constraints.

    Checks:
    - Speed (byte 3) is within reasonable range

    Args:
        frame: 5-byte SPEED frame

    Returns:
        Tuple of (is_valid, error_message)
    """
    if len(frame) != MSG_SIZE_SPEED:
        return False, f"SPEED frame must be 5 bytes, got {len(frame)}"

    speed = frame[3]
    if speed < SPEED_MIN or speed > SPEED_MAX:
        return False, f"Speed value {speed} is outside range {SPEED_MIN}-{SPEED_MAX}"

    return True, ""


def validate_frame(frame: bytes) -> tuple[bool, str]:
    """Perform full validation on a frame.

    Validates in order:
    1. Frame structure
    2. Type and size match
    3. Field constraints (for DATA and SPEED)

    Args:
        frame: Raw frame bytes

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Structure validation
    if not is_valid_frame(frame):
        return False, "Invalid frame structure"

    # Type/size validation
    valid, error = validate_frame_type(frame)
    if not valid:
        return False, error

    # Field validation for specific types
    type_byte = frame[2]

    if type_byte == MSG_TYPE_DATA:
        return validate_data_fields(frame)

    if type_byte == MSG_TYPE_SPEED:
        return validate_speed_fields(frame)

    # IDLE messages don't need field validation
    return True, ""

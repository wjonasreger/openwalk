"""Protocol parser for InMovement Unsit treadmill BLE messages.

This is the main entry point for parsing BLE notifications.
Handles frame splitting, type detection, field extraction, and validation.
"""

import struct
from datetime import datetime

from openwalk.ble.characteristics import (
    MSG_TYPE_DATA,
    MSG_TYPE_IDLE,
    MSG_TYPE_SPEED,
)
from openwalk.protocol.frames import split_frames
from openwalk.protocol.messages import (
    AnyFrame,
    DataMessage,
    IdleMessage,
    Message,
    SpeedMessage,
    TruncatedFrame,
)
from openwalk.protocol.validators import (
    get_truncation_variant,
    is_truncated_data,
    is_valid_frame,
    validate_frame,
)


def parse_idle(frame: bytes, timestamp: datetime) -> IdleMessage:
    """Parse an IDLE message frame.

    IDLE structure (7 bytes):
    [5B] [04] [03] [state1] [state2] [state3] [5D]

    Args:
        frame: 7-byte IDLE frame
        timestamp: Message timestamp

    Returns:
        IdleMessage with extracted fields
    """
    return IdleMessage(
        timestamp=timestamp,
        state_byte1=frame[3],
        state_byte2=frame[4],
        state_byte3=frame[5],
        raw_hex=frame.hex(),
    )


def parse_speed(frame: bytes, timestamp: datetime) -> SpeedMessage:
    """Parse a SPEED message frame.

    SPEED structure (5 bytes):
    [5B] [02] [11] [speed] [5D]

    Args:
        frame: 5-byte SPEED frame
        timestamp: Message timestamp

    Returns:
        SpeedMessage with extracted fields
    """
    return SpeedMessage(
        timestamp=timestamp,
        speed=frame[3],
        raw_hex=frame.hex(),
    )


def parse_data(frame: bytes, timestamp: datetime) -> DataMessage:
    """Parse a DATA message frame.

    DATA structure (16 bytes):
    [5B] [0D] [05] [flag] [belt_cadence] [00] [dist_L] [dist_H]
    [belt_revs] [00] [steps_H] [steps_L] [speed] [belt_state] [00] [5D]

    Args:
        frame: 16-byte DATA frame
        timestamp: Message timestamp

    Returns:
        DataMessage with extracted fields
    """
    # Distance is uint16 little-endian
    distance_raw = struct.unpack_from("<H", frame, 6)[0]
    # Steps (actual footstep counter) is uint16 big-endian
    steps = struct.unpack_from(">H", frame, 10)[0]

    return DataMessage(
        timestamp=timestamp,
        flag=frame[3],
        belt_cadence=frame[4],
        distance_raw=distance_raw,
        belt_revs=frame[8],
        steps=steps,
        speed=frame[12],
        belt_state=frame[13],
        raw_hex=frame.hex(),
    )


def parse_frame(frame: bytes, timestamp: datetime | None = None) -> AnyFrame | None:
    """Parse a single frame into a message object.

    Args:
        frame: Raw frame bytes
        timestamp: Message timestamp (defaults to now)

    Returns:
        Message object (IdleMessage, SpeedMessage, DataMessage, or TruncatedFrame)
        None if frame is invalid and cannot be parsed
    """
    if timestamp is None:
        timestamp = datetime.now()

    # Check for truncated DATA frames first
    if is_truncated_data(frame):
        return TruncatedFrame(
            timestamp=timestamp,
            expected_size=16,
            actual_size=len(frame),
            variant=get_truncation_variant(frame),
            raw_hex=frame.hex(),
        )

    # Validate frame structure
    if not is_valid_frame(frame):
        return None

    # Validate type and fields
    valid, error = validate_frame(frame)
    if not valid:
        # Could log error here
        return None

    # Parse based on type
    type_byte = frame[2]

    if type_byte == MSG_TYPE_IDLE:
        return parse_idle(frame, timestamp)

    if type_byte == MSG_TYPE_SPEED:
        return parse_speed(frame, timestamp)

    if type_byte == MSG_TYPE_DATA:
        return parse_data(frame, timestamp)

    # Unknown type - should not reach here if validation passed
    return None


def parse_notification(data: bytes, timestamp: datetime | None = None) -> list[AnyFrame]:
    """Parse a BLE notification containing one or more frames.

    BLE notifications may contain multiple concatenated messages.
    This function splits them and parses each frame.

    Args:
        data: Raw bytes from BLE notification
        timestamp: Timestamp for all messages (defaults to now)

    Returns:
        List of parsed message objects
        May include TruncatedFrame objects for invalid frames

    Example:
        >>> # Notification with SPEED + DATA messages
        >>> data = bytes.fromhex("5b02110f5d5b0d05023f00370019004a0a0f01005d")
        >>> messages = parse_notification(data)
        >>> len(messages)
        2
        >>> messages[0].message_type
        'speed'
        >>> messages[1].message_type
        'data'
    """
    if timestamp is None:
        timestamp = datetime.now()

    frames = split_frames(data)
    messages: list[AnyFrame] = []

    for frame in frames:
        parsed = parse_frame(frame, timestamp)
        if parsed is not None:
            messages.append(parsed)

    return messages


def filter_valid_messages(frames: list[AnyFrame]) -> list[Message]:
    """Filter a list of frames to only valid messages (excluding truncated).

    Args:
        frames: List of parsed frames (may include TruncatedFrame)

    Returns:
        List of valid messages only (IdleMessage, SpeedMessage, DataMessage)
    """
    return [f for f in frames if not isinstance(f, TruncatedFrame)]


def filter_data_messages(frames: list[AnyFrame]) -> list[DataMessage]:
    """Filter a list of frames to only DATA messages.

    Args:
        frames: List of parsed frames

    Returns:
        List of DataMessage objects only
    """
    return [f for f in frames if isinstance(f, DataMessage)]


def filter_truncated_frames(frames: list[AnyFrame]) -> list[TruncatedFrame]:
    """Filter a list of frames to only truncated frames.

    Args:
        frames: List of parsed frames

    Returns:
        List of TruncatedFrame objects only
    """
    return [f for f in frames if isinstance(f, TruncatedFrame)]

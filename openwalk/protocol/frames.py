"""Frame splitting for BLE notifications containing concatenated messages.

BLE notifications may contain multiple messages concatenated together.
Each message is delimited by 0x5B (start) and 0x5D (end) markers.

Example: A 21-byte notification might contain:
- 5-byte SPEED message: 5b 02 11 0f 5d
- 16-byte DATA message: 5b 0d 05 02 3f 00 37 00 19 00 45 0a 0f 01 00 5d
"""

from openwalk.ble.characteristics import FRAME_END, FRAME_START


def split_frames(data: bytes) -> list[bytes]:
    """Split a BLE notification into individual frames.

    Uses two methods to find frame boundaries:
    1. Length-byte method (preferred): Use byte[1] to calculate expected end position
    2. Marker scanning (fallback): Scan for 0x5D end marker

    Args:
        data: Raw bytes from BLE notification

    Returns:
        List of individual frames, each starting with 0x5B and ending with 0x5D

    Example:
        >>> data = bytes.fromhex("5b02110f5d5b0d05023f00370019004a0a0f01005d")
        >>> frames = split_frames(data)
        >>> len(frames)
        2
        >>> frames[0].hex()
        '5b02110f5d'
    """
    frames: list[bytes] = []
    i = 0

    while i < len(data):
        # Skip until we find a start marker
        if data[i] != FRAME_START:
            i += 1
            continue

        start_idx = i

        # Method 1: Use length byte to find frame end
        if i + 1 < len(data):
            length_byte = data[i + 1]
            # Total frame size = 1 (start) + 1 (length) + payload_length + 1 (end)
            expected_end = i + length_byte + 2

            if expected_end < len(data) and data[expected_end] == FRAME_END:
                frame = data[start_idx : expected_end + 1]
                frames.append(frame)
                i = expected_end + 1
                continue

        # Method 2: Scan for end marker (fallback for malformed frames)
        end_idx = None
        for j in range(i + 1, len(data)):
            if data[j] == FRAME_END:
                end_idx = j
                break
            elif data[j] == FRAME_START:
                # Found another start before end - this frame is incomplete
                break

        if end_idx is not None:
            frame = data[start_idx : end_idx + 1]
            frames.append(frame)
            i = end_idx + 1
        else:
            # No end marker found - incomplete frame at end of buffer
            break

    return frames


def extract_frame_info(frame: bytes) -> dict[str, int | str]:
    """Extract basic information from a frame for debugging.

    Args:
        frame: A single frame starting with 0x5B and ending with 0x5D

    Returns:
        Dictionary with frame info:
        - total_size: Total bytes in frame
        - length_byte: Value of length byte (expected payload size)
        - type_byte: Message type code
        - hex: Hex string representation
    """
    if len(frame) < 3:
        return {
            "total_size": len(frame),
            "length_byte": -1,
            "type_byte": -1,
            "hex": frame.hex(),
        }

    return {
        "total_size": len(frame),
        "length_byte": frame[1],
        "type_byte": frame[2],
        "hex": frame.hex(),
    }

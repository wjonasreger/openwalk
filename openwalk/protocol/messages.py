"""Message dataclasses for InMovement Unsit treadmill BLE protocol.

Three message types:
- IdleMessage (0x03): Sent when belt is stopped, ~1/sec heartbeat
- SpeedMessage (0x11): Speed change notification
- DataMessage (0x05): Primary telemetry with steps, distance, speed, etc.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class IdleMessage:
    """IDLE message - sent when treadmill belt is stopped.

    Total size: 7 bytes
    Structure: [5B] [04] [03] [state1] [state2] [state3] [5D]

    Sent approximately once per second when powered on but not walking.
    """

    timestamp: datetime
    state_byte1: int  # byte 3: observed values 1, 2, 3
    state_byte2: int  # byte 4: always 1
    state_byte3: int  # byte 5: always 0
    raw_hex: str

    @property
    def message_type(self) -> str:
        return "idle"


@dataclass(frozen=True)
class SpeedMessage:
    """SPEED message - speed setting notification.

    Total size: 5 bytes
    Structure: [5B] [02] [11] [speed] [5D]

    Sent when speed changes and periodically (~3 sec) as keepalive during walking.
    Speed is a raw setting level (1-20), NOT mph.
    """

    timestamp: datetime
    speed: int  # 1-20, where 20 = max speed
    raw_hex: str

    @property
    def message_type(self) -> str:
        return "speed"

    @property
    def speed_mph(self) -> float:
        """Convert speed setting to approximate mph.

        Speed setting 1-20 maps roughly to 0.1-2.0 mph.
        """
        return self.speed / 10.0


@dataclass(frozen=True)
class DataMessage:
    """DATA message - primary telemetry packet.

    Total size: 16 bytes
    Structure: [5B] [0D] [05] [flag] [belt_cadence] [00] [dist_L] [dist_H]
               [belt_revs] [00] [steps_H] [steps_L] [speed] [belt_state] [00] [5D]

    Sent approximately 2 times per second while belt is running.
    Contains cumulative counters that wrap at their max values.
    """

    timestamp: datetime
    flag: int  # byte 3: 0-7, cycles during session (purpose unknown)
    belt_cadence: int  # byte 4: uint8, belt-derived cadence (~2.55:1 to belt_revs)
    distance_raw: int  # bytes 6-7: uint16 LE, hundredths of a mile
    belt_revs: int  # byte 8: uint8, wraps at 255
    steps: int  # bytes 10-11: uint16 BE, actual footstep counter
    speed: int  # byte 12: 1-20 setting level
    belt_state: int  # byte 13: 1 = running
    raw_hex: str

    @property
    def message_type(self) -> str:
        return "data"

    @property
    def distance_miles(self) -> float:
        """Convert raw distance to miles."""
        return self.distance_raw / 100.0

    @property
    def speed_mph(self) -> float:
        """Convert speed setting to approximate mph."""
        return self.speed / 10.0

    @property
    def is_belt_running(self) -> bool:
        """Check if belt is currently running."""
        return self.belt_state == 1


@dataclass(frozen=True)
class TruncatedFrame:
    """Represents a truncated frame that failed validation.

    Truncated frames occur when BLE notifications are cut off mid-transmission.
    Expected rate: ~0.7% of messages.
    These are logged but not processed as telemetry.
    """

    timestamp: datetime
    expected_size: int
    actual_size: int
    variant: str  # e.g., "DATA_5", "DATA_9", "DATA_12"
    raw_hex: str

    @property
    def message_type(self) -> str:
        return "truncated"


# Union type for all valid message types
Message = IdleMessage | SpeedMessage | DataMessage

# Union type including truncated frames
AnyFrame = IdleMessage | SpeedMessage | DataMessage | TruncatedFrame

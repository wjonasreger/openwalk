#!/usr/bin/env python3
"""Capture raw BLE notifications for a 60-second controlled trial.

Test protocol:
  1. Start treadmill at full speed (setting 20)
  2. Run this script
  3. Phase 1 (0-30s): Walk on the belt
  4. Phase 2 (30-60s): Step off the belt (belt still running)
  5. Script auto-stops at 60 seconds

Output: scripts/trial_data/trial_YYYYMMDD_HHMMSS.jsonl
Each line is a JSON object with timestamp, raw hex, and parsed bytes.
"""

import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from bleak import BleakClient, BleakScanner

# ISSC Transparent UART — primary notify characteristic
NOTIFY_UUID = "49535343-1e4d-4bd9-ba61-23c647249616"
DEVICE_NAME = "BM70_DT"

TRIAL_DURATION = 60  # seconds
PHASE_SWITCH = 30  # seconds — walk for 30, off for 30

# Output directory
TRIAL_DIR = Path(__file__).parent / "trial_data"


async def main() -> None:
    TRIAL_DIR.mkdir(parents=True, exist_ok=True)

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = TRIAL_DIR / f"trial_{timestamp_str}.jsonl"

    print(f"Scanning for {DEVICE_NAME}...")
    device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=15.0)
    if device is None:
        print(f"ERROR: Could not find {DEVICE_NAME}. Is the treadmill on?")
        sys.exit(1)

    print(f"Found: {device.name} ({device.address})")

    notifications: list[dict] = []
    start_time: float = 0.0

    def on_notify(sender: object, data: bytearray) -> None:
        now = time.time()
        elapsed = now - start_time if start_time > 0 else 0.0
        phase = 1 if elapsed <= PHASE_SWITCH else 2
        raw_bytes = list(data)

        record = {
            "timestamp": datetime.now().isoformat(),
            "elapsed_s": round(elapsed, 4),
            "phase": phase,
            "raw_hex": data.hex(),
            "raw_bytes": raw_bytes,
            "length": len(data),
        }
        notifications.append(record)

        # Live progress indicator
        msg_type = "?"
        if len(raw_bytes) >= 3:
            type_byte = raw_bytes[2]
            if type_byte == 0x05:
                msg_type = "DATA"
            elif type_byte == 0x03:
                msg_type = "IDLE"
            elif type_byte == 0x11:
                msg_type = "SPEED"

        phase_label = "WALKING" if phase == 1 else "OFF-BELT"
        print(
            f"  [{elapsed:6.1f}s] Phase {phase} ({phase_label}) | "
            f"{msg_type:5s} | {len(raw_bytes):2d} bytes | {data.hex()}",
            end="\r",
        )

    print(f"Connecting to {device.address}...")
    async with BleakClient(device.address, timeout=10.0) as client:
        print(f"Connected. Subscribing to notifications...")
        await client.start_notify(NOTIFY_UUID, on_notify)

        print()
        print("=" * 72)
        print(f"  TRIAL STARTED — {TRIAL_DURATION}s total")
        print(f"  Phase 1 (0-{PHASE_SWITCH}s):  WALK on the belt at full speed")
        print(f"  Phase 2 ({PHASE_SWITCH}-{TRIAL_DURATION}s): STEP OFF (belt still running)")
        print("=" * 72)
        print()

        start_time = time.time()

        # Wait for trial duration
        while (time.time() - start_time) < TRIAL_DURATION:
            elapsed = time.time() - start_time
            if abs(elapsed - PHASE_SWITCH) < 0.3 and elapsed < PHASE_SWITCH + 0.5:
                print()
                print()
                print(">>> PHASE 2: STEP OFF THE BELT NOW <<<")
                print()
            await asyncio.sleep(0.1)

        print()
        print()
        await client.stop_notify(NOTIFY_UUID)

    # Write output
    with open(output_path, "w") as f:
        for record in notifications:
            f.write(json.dumps(record) + "\n")

    # Summary
    phase1 = [r for r in notifications if r["phase"] == 1]
    phase2 = [r for r in notifications if r["phase"] == 2]

    print("=" * 72)
    print(f"  TRIAL COMPLETE")
    print(f"  Total notifications: {len(notifications)}")
    print(f"  Phase 1 (walking):   {len(phase1)} notifications")
    print(f"  Phase 2 (off-belt):  {len(phase2)} notifications")
    print(f"  Output: {output_path}")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())

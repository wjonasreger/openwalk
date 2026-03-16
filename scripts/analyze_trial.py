#!/usr/bin/env python3
"""Analyze a capture trial JSONL file for step detection signals.

Compares Phase 1 (walking) vs Phase 2 (off-belt) across all DATA message
bytes to find any differences that could indicate actual footstep detection.

Usage:
    uv run python scripts/analyze_trial.py scripts/trial_data/trial_*.jsonl
"""

import json
import sys
from collections import Counter
from pathlib import Path


def parse_data_messages(records: list[dict]) -> list[dict]:
    """Filter to DATA messages (type 0x05) with 16 bytes."""
    data_msgs = []
    for r in records:
        raw = r["raw_bytes"]
        # A single notification can contain multiple concatenated messages.
        # Split on 0x5B start markers and parse each 16-byte DATA frame.
        i = 0
        while i < len(raw):
            if raw[i] == 0x5B:
                # Check for DATA message: length byte = 0x0D, type = 0x05
                if i + 2 < len(raw) and raw[i + 1] == 0x0D and raw[i + 2] == 0x05:
                    if i + 16 <= len(raw) and raw[i + 15] == 0x5D:
                        frame = raw[i : i + 16]
                        data_msgs.append(
                            {
                                "timestamp": r["timestamp"],
                                "elapsed_s": r["elapsed_s"],
                                "phase": r["phase"],
                                "bytes": frame,
                                "raw_hex": bytes(frame).hex(),
                            }
                        )
                        i += 16
                        continue
                # Check for SPEED message (5 bytes)
                if i + 2 < len(raw) and raw[i + 1] == 0x02 and raw[i + 2] == 0x11:
                    i += 5
                    continue
                # Check for IDLE message (7 bytes)
                if i + 2 < len(raw) and raw[i + 1] == 0x04 and raw[i + 2] == 0x03:
                    i += 7
                    continue
            i += 1
    return data_msgs


def analyze_byte_distributions(
    phase1: list[dict], phase2: list[dict], byte_names: dict[int, str]
) -> None:
    """Compare byte value distributions between phases."""
    print("\n" + "=" * 72)
    print("BYTE VALUE DISTRIBUTIONS (Phase 1 vs Phase 2)")
    print("=" * 72)

    for pos, name in sorted(byte_names.items()):
        vals1 = [m["bytes"][pos] for m in phase1]
        vals2 = [m["bytes"][pos] for m in phase2]

        c1 = Counter(vals1)
        c2 = Counter(vals2)

        unique1 = len(c1)
        unique2 = len(c2)
        min1, max1 = (min(vals1), max(vals1)) if vals1 else (0, 0)
        min2, max2 = (min(vals2), max(vals2)) if vals2 else (0, 0)

        print(f"\n  Byte {pos:2d} ({name}):")
        print(f"    Phase 1: {len(vals1)} samples, range [{min1}-{max1}], {unique1} unique values")
        print(f"    Phase 2: {len(vals2)} samples, range [{min2}-{max2}], {unique2} unique values")

        # Show top values if interesting
        if unique1 > 1 or unique2 > 1:
            top1 = c1.most_common(5)
            top2 = c2.most_common(5)
            print(f"    Phase 1 top: {top1}")
            print(f"    Phase 2 top: {top2}")


def analyze_increment_rates(phase1: list[dict], phase2: list[dict]) -> None:
    """Compare how fast counters increment in each phase."""
    print("\n" + "=" * 72)
    print("INCREMENT RATE ANALYSIS")
    print("=" * 72)

    fields = [
        (4, "belt_cadence (byte 4)"),
        (8, "belt_revs (byte 8)"),
    ]

    for byte_pos, name in fields:
        for phase_name, msgs in [("Phase 1 (walking)", phase1), ("Phase 2 (off-belt)", phase2)]:
            if len(msgs) < 2:
                continue

            deltas = []
            time_deltas = []
            for i in range(1, len(msgs)):
                prev_val = msgs[i - 1]["bytes"][byte_pos]
                curr_val = msgs[i]["bytes"][byte_pos]
                delta = curr_val - prev_val
                if delta < 0:
                    delta += 256  # wrap
                deltas.append(delta)

                dt = msgs[i]["elapsed_s"] - msgs[i - 1]["elapsed_s"]
                time_deltas.append(dt)

            total_increments = sum(deltas)
            duration = msgs[-1]["elapsed_s"] - msgs[0]["elapsed_s"]
            rate = total_increments / duration if duration > 0 else 0

            print(f"\n  {name} — {phase_name}:")
            print(f"    Total increments: {total_increments} over {duration:.1f}s")
            print(f"    Rate: {rate:.2f} /sec")
            print(f"    Messages: {len(msgs)}")

    # Motor pulses (bytes 10-11, big-endian based on analysis)
    print(f"\n  motor_pulses (bytes 10-11 BE):")
    for phase_name, msgs in [("Phase 1 (walking)", phase1), ("Phase 2 (off-belt)", phase2)]:
        if len(msgs) < 2:
            continue

        motor_vals = [m["bytes"][10] * 256 + m["bytes"][11] for m in msgs]
        deltas = []
        for i in range(1, len(motor_vals)):
            d = motor_vals[i] - motor_vals[i - 1]
            if d < 0:
                d += 65536
            deltas.append(d)

        total = sum(deltas)
        duration = msgs[-1]["elapsed_s"] - msgs[0]["elapsed_s"]
        rate = total / duration if duration > 0 else 0
        avg_delta = sum(deltas) / len(deltas) if deltas else 0

        print(f"    {phase_name}: {total} pulses over {duration:.1f}s = {rate:.1f}/sec")
        print(f"      avg delta per msg: {avg_delta:.2f}, min: {min(deltas)}, max: {max(deltas)}")


def analyze_step_timing(phase1: list[dict], phase2: list[dict]) -> None:
    """Analyze the timing of step counter increments."""
    print("\n" + "=" * 72)
    print("STEP INCREMENT TIMING")
    print("=" * 72)

    for phase_name, msgs in [("Phase 1 (walking)", phase1), ("Phase 2 (off-belt)", phase2)]:
        if len(msgs) < 2:
            continue

        # Find timestamps where byte 4 (steps) actually changes
        change_times = []
        for i in range(1, len(msgs)):
            if msgs[i]["bytes"][4] != msgs[i - 1]["bytes"][4]:
                change_times.append(msgs[i]["elapsed_s"])

        if len(change_times) < 2:
            print(f"\n  {phase_name}: {len(change_times)} step changes (insufficient for timing)")
            continue

        intervals = [change_times[i] - change_times[i - 1] for i in range(1, len(change_times))]

        avg_interval = sum(intervals) / len(intervals)
        min_interval = min(intervals)
        max_interval = max(intervals)

        print(f"\n  {phase_name}:")
        print(f"    Step changes: {len(change_times)}")
        print(f"    Avg interval: {avg_interval:.3f}s")
        print(f"    Min interval: {min_interval:.3f}s")
        print(f"    Max interval: {max_interval:.3f}s")
        print(f"    Std dev: {_stddev(intervals):.3f}s")


def analyze_flag_patterns(phase1: list[dict], phase2: list[dict]) -> None:
    """Compare flag byte (byte 3) patterns between phases."""
    print("\n" + "=" * 72)
    print("FLAG BYTE (BYTE 3) PATTERNS")
    print("=" * 72)

    for phase_name, msgs in [("Phase 1 (walking)", phase1), ("Phase 2 (off-belt)", phase2)]:
        flags = [m["bytes"][3] for m in msgs]
        counter = Counter(flags)
        print(f"\n  {phase_name}: {dict(sorted(counter.items()))}")

        # Check if flag transitions correlate with step changes
        transitions_with_step = 0
        transitions_without_step = 0
        for i in range(1, len(msgs)):
            if msgs[i]["bytes"][3] != msgs[i - 1]["bytes"][3]:
                if msgs[i]["bytes"][4] != msgs[i - 1]["bytes"][4]:
                    transitions_with_step += 1
                else:
                    transitions_without_step += 1
        print(
            f"    Flag transitions with step change: {transitions_with_step}, "
            f"without: {transitions_without_step}"
        )


def _stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return variance**0.5


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python analyze_trial.py <trial_file.jsonl>")
        sys.exit(1)

    filepath = Path(sys.argv[1])
    if not filepath.exists():
        print(f"File not found: {filepath}")
        sys.exit(1)

    print(f"Loading {filepath}...")
    with open(filepath) as f:
        records = [json.loads(line) for line in f]

    print(f"Total notifications: {len(records)}")

    # Parse DATA messages from raw notifications
    data_msgs = parse_data_messages(records)
    print(f"DATA messages parsed: {len(data_msgs)}")

    phase1 = [m for m in data_msgs if m["phase"] == 1]
    phase2 = [m for m in data_msgs if m["phase"] == 2]
    print(f"Phase 1 (walking): {len(phase1)} DATA messages")
    print(f"Phase 2 (off-belt): {len(phase2)} DATA messages")

    if not phase1 or not phase2:
        print("ERROR: Need DATA messages in both phases for comparison.")
        sys.exit(1)

    # Byte name map for DATA message
    byte_names = {
        0: "start (0x5B)",
        1: "length (0x0D)",
        2: "type (0x05)",
        3: "flag",
        4: "belt_cadence",
        5: "reserved1",
        6: "dist_lo",
        7: "dist_hi",
        8: "belt_revs",
        9: "reserved2",
        10: "steps_hi (BE)",
        11: "steps_lo (BE)",
        12: "speed",
        13: "belt_state",
        14: "padding",
        15: "end (0x5D)",
    }

    analyze_byte_distributions(phase1, phase2, byte_names)
    analyze_increment_rates(phase1, phase2)
    analyze_step_timing(phase1, phase2)
    analyze_flag_patterns(phase1, phase2)

    print("\n" + "=" * 72)
    print("ANALYSIS COMPLETE")
    print("=" * 72)
    print()
    print("Key things to look for:")
    print("  1. Motor pulse rate different between phases (belt load detection)")
    print("  2. Step increment rate different between phases")
    print("  3. Flag byte distribution different between phases")
    print("  4. Any 'reserved' byte becoming non-zero")
    print("  5. Step timing regularity (walking should be rhythmic, belt-derived should be constant)")


if __name__ == "__main__":
    main()

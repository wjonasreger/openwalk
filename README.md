# OpenWalk

A macOS terminal app for the InMovement Unsit under-desk treadmill.

## What is this?

OpenWalk connects to the Unsit treadmill via Bluetooth, captures your walking sessions in real-time, and syncs your steps, distance, and calories to Apple Health. Your walks automatically appear on your iPhone and Apple Watch alongside your other fitness data.

## Why build this?

The official InMovement app has connection issues, inaccurate data, and limited usefulness. I wanted a simple, reliable way to track my under-desk walks without having to manually log anything or wonder if my data was accurate or even synced to Apple Health correctly. Walk, and the data just shows up in Health.

## How it works

The treadmill has a Bluetooth Low Energy (BLE) module that broadcasts your walking data — steps, distance, speed, and belt state. OpenWalk listens to this data stream, tracks your session locally, and periodically syncs to Apple Health in the background.

The design philosophy is simple: **walk without thinking about it**. No buttons to press, no app to open. Just step on and go.

## Status

**Currently in development.** The core protocol parser is complete and validated against real hardware. Working toward a functional terminal UI with live session tracking.

## Requirements

- macOS 14 (Sonoma) or later
- InMovement Unsit treadmill
- Python 3.11+

## License

Apache 2.0

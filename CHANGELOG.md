# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-03-15

### Added
- BLE connection manager with auto-reconnect and exponential backoff
- Protocol parser for InMovement Unsit BLE data (IDLE/SPEED/DATA messages)
- uint8 wrap-around tracking for step and belt revolution counters
- Live TUI dashboard with real-time metrics and sparklines (2 Hz refresh)
- SQLite persistence for sessions and raw telemetry samples
- Auto-session detection (start on belt running, end after 60s inactivity)
- Calorie calculation using LCDA Walking Equation and Mifflin-St Jeor BMR
- `openwalk run` command with interactive TUI dashboard
- `openwalk history` command to list past sessions
- `openwalk export` command with CSV and JSON output
- `openwalk config` commands for user profile management
- Crash recovery for sessions interrupted by unexpected exits
- Configurable user profile via `~/.openwalk/config.toml`
- Truncated frame detection and error logging

### Removed
- HealthKit sync pipeline (HealthKit data store unavailable on macOS)
- Swift health bridge package (`openwalk-health-bridge`)

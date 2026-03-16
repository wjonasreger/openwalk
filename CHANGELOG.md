# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [1.0.1] - 2026-03-15

### Fixed
- Step counter rewired to bytes 10-11 (uint16 BE) — actual footsteps, not belt-derived cadence
- Flag validation relaxed (was silently dropping all DATA messages for flag values > 10)
- Session history: steps and distance now session-relative instead of cumulative treadmill counters
- Session history: duration, calories, and avg speed no longer overwritten with NULLs at finalization
- Avg speed computed from running average of speed readings instead of broken distance/time formula
- Crash recovery computes correct session deltas from sample data

### Changed
- Calories only accumulate while actively stepping (step_rate > 0)
- Sparkline window configurable via `[display] sparkline_minutes` in config (default 15 min, was hardcoded 60 min)
- Debug logging writes to `/tmp/openwalk_debug.log` instead of stderr

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

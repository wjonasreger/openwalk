# OpenWalk

A macOS terminal app for the InMovement Unsit under-desk treadmill. Connects via Bluetooth, tracks your walks in real-time, and stores everything locally.

## What is this?

OpenWalk listens to your Unsit treadmill's BLE data stream and gives you a live terminal dashboard showing steps, distance, speed, calories, and sparkline graphs. Sessions are automatically detected, recorded to SQLite, and available for export.

## Why build this?

The official InMovement app has connection issues, inaccurate data, and limited usefulness. I wanted a simple, reliable way to track my under-desk walks without having to manually log anything or wonder if my data was accurate. Step on and go.

## Features

- **BLE auto-connect** with reconnection and exponential backoff
- **Live TUI dashboard** refreshing at 2 Hz with metrics grid and sparklines
- **Real-time tracking** of steps, distance, speed, calories, step rate, and max speed
- **Auto-session detection** — starts on belt running, ends after 60s inactivity
- **SQLite persistence** — sessions and raw samples stored locally
- **History and export** — view past sessions, export to CSV or JSON
- **Calorie calculation** using LCDA Walking Equation and Mifflin-St Jeor BMR
- **Crash recovery** — interrupted sessions are finalized on next startup
- **Configurable user profile** for accurate calorie estimates

## Quick Start

### Prerequisites

- macOS 14 (Sonoma) or later
- Python 3.11+
- InMovement Unsit treadmill (powered on)
- Bluetooth permissions for your terminal app

### Install

```bash
# One-liner (install directly from GitHub)
pip install git+https://github.com/wjonasreger/openwalk.git

# Or clone and install locally
git clone https://github.com/wjonasreger/openwalk.git
cd openwalk
pip install .
```

### Bluetooth Permissions

Your terminal needs Bluetooth access. Go to **System Settings > Privacy & Security > Bluetooth** and add your terminal app (Terminal.app, iTerm2, Ghostty, etc.).

### Run

```bash
openwalk run
```

The dashboard appears and auto-connects to your treadmill. Start walking — the session begins automatically.

Press `q` to quit, `r` to manually reconnect.

## CLI Reference

| Command | Description |
|---------|-------------|
| `openwalk run` | Start the live TUI dashboard |
| `openwalk run --debug` | Dashboard with debug logging |
| `openwalk history` | List past sessions |
| `openwalk history -n 20` | Show last 20 sessions |
| `openwalk export <ID>` | Export a session to CSV (stdout) |
| `openwalk export <ID> --format json` | Export as JSON |
| `openwalk export --all -o data.csv` | Export all sessions to file |
| `openwalk config show` | Display current configuration |
| `openwalk config init` | Create default config file |

## How It Works

```
Treadmill (BLE) -> Protocol Parser -> Session Orchestrator -> SQLite
                                            |
                                      Live TUI Dashboard
```

1. **BLE Layer** — discovers and connects to the treadmill using the ISSC Transparent UART service
2. **Protocol Parser** — splits concatenated BLE notifications into frames, parses IDLE/SPEED/DATA messages, tracks uint8 counter wrap-around
3. **Session Orchestrator** — bridges sync BLE callbacks to async DB writes via queue, manages session lifecycle
4. **Storage** — SQLite with sessions, samples, and error_log tables
5. **TUI** — Rich Live dashboard rendering metrics, sparklines, and connection status at 2 Hz

## Configuration

User profile is stored at `~/.openwalk/config.toml` and used for calorie calculation:

```toml
[user]
weight_lbs = 180.0
height_inches = 70.0
age_years = 30
gender = "male"
```

Create the default config with `openwalk config init`, then edit to match your profile.

## Troubleshooting

**Device not found**
- Make sure the treadmill is powered on (check the display)
- Force-close the Unsit app on your phone — it holds an exclusive BLE connection
- Move your Mac within 10 feet of the treadmill
- Verify your terminal has Bluetooth permissions

**Connection drops immediately**
- The phone app holds an exclusive connection. Close the Unsit app or disable Bluetooth on your phone.

**Truncated frames (~0.7% normal)**
- A small number of BLE messages arrive incomplete. These are automatically detected and skipped. This is normal BLE behavior and does not affect data quality.

## Development

```bash
git clone https://github.com/wjonasreger/openwalk.git
cd openwalk
uv sync

# Run tests
uv run pytest -v

# Lint
uv run ruff check openwalk/ tests/

# Type check
uv run mypy openwalk/

# Format check
uv run black --check openwalk/ tests/
```

155 tests covering BLE, protocol parsing, storage, session management, CLI, and TUI rendering.

## Future

Apple Health integration is planned as a separate iOS companion app (`openwalk-ios`), since HealthKit's data store is not available on macOS.

## License

Apache 2.0

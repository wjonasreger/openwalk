"""Rich-based dashboard renderer for live session display.

Pure rendering: takes state, returns Rich renderables. No I/O, no async, no BLE.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

from rich import box
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from openwalk.ble.connection import ConnectionState
from openwalk.session.state import LiveSessionState

# Sparkline characters: space + 8 gradient levels
SPARKLINE_CHARS = " ▁▂▃▄▅▆▇█"


def render_dashboard(
    state: LiveSessionState,
    conn_state: ConnectionState,
    conn_message: str,
    total_messages: int,
) -> Panel:
    """Build the complete dashboard panel from current state."""
    parts: list[RenderableType] = [
        render_metrics_table(state),
        Text(),
        render_sparklines(state),
        Text(),
        render_status_bar(
            conn_state,
            conn_message,
            state.session_id,
            total_messages,
            state.truncated_count,
        ),
    ]
    return Panel(
        Group(*parts),
        title="[bold cyan]OpenWalk — Live Session[/bold cyan]",
        box=box.ROUNDED,
        padding=(1, 2),
    )


def render_metrics_table(state: LiveSessionState) -> Table:
    """2x4 grid: Steps/Speed, Time/Belt, Distance/Pace, Calories/Burn."""
    table = Table(show_header=False, box=None, padding=(0, 3))
    table.add_column("label_l", style="dim", width=12)
    table.add_column("value_l", style="bold white", width=16)
    table.add_column("label_r", style="dim", width=12)
    table.add_column("value_r", style="bold white", width=16)

    belt_text = Text(
        "Running" if state.is_belt_running else "Stopped",
        style="bold green" if state.is_belt_running else "bold yellow",
    )

    table.add_row("Steps:", f"{state.total_steps:,}", "Speed:", f"{state.speed}/20")
    table.add_row("Time:", state.elapsed_formatted, "Belt:", belt_text)
    table.add_row(
        "Distance:", f"{state.distance_miles:.2f} mi", "Pace:", f"~{state.speed_mph:.1f} mph"
    )
    table.add_row(
        "Calories:",
        f"{state.net_calories:.0f} kcal",
        "Burn:",
        f"{state.net_cal_per_min:.1f} kcal/min",
    )
    table.add_row(
        "Step Rate:",
        f"{state.step_rate:.0f} /min",
        "Max Speed:",
        f"{state.max_speed}/20",
    )
    return table


def render_sparklines(state: LiveSessionState) -> Group:
    """Render speed, step rate, and calorie sparklines."""
    now = datetime.now()
    window_ago = now - timedelta(minutes=state.sparkline_minutes)
    start = state.started_at or now
    sparkline_start = max(start, window_ago)
    width = 40

    # Active window length (capped at sparkline_minutes)
    active_seconds = (now - sparkline_start).total_seconds()
    active_min = int(active_seconds) // 60
    active_sec = int(active_seconds) % 60

    speed_vals = _extract_sparkline_values(state.speed_history, sparkline_start, now, width)
    rate_vals = _extract_sparkline_values(state.step_rate_history, sparkline_start, now, width)
    cal_vals = _extract_sparkline_values(state.calorie_history, sparkline_start, now, width)

    speed_line = render_sparkline(speed_vals, max_val=20.0)
    rate_line = render_sparkline(rate_vals)
    cal_line = render_sparkline(cal_vals)

    header = Text()
    header.append(
        f"  Sparklines ({active_min}:{active_sec:02d} / {state.sparkline_minutes}:00)",
        style="dim",
    )

    speed_text = Text()
    speed_text.append("  Speed:     ", style="dim")
    speed_text.append(speed_line, style="cyan")

    rate_text = Text()
    rate_text.append("  Step Rate: ", style="dim")
    rate_text.append(rate_line, style="green")

    cal_text = Text()
    cal_text.append("  Calories:  ", style="dim")
    cal_text.append(cal_line, style="yellow")

    return Group(header, speed_text, rate_text, cal_text)


def render_status_bar(
    conn_state: ConnectionState,
    conn_message: str,
    session_id: int | None,
    total_messages: int,
    truncated_count: int,
) -> Text:
    """Connection status indicator, session info, message counts."""
    text = Text()
    text.append("  BLE: ", style="dim")

    if conn_state in (ConnectionState.SUBSCRIBED, ConnectionState.CONNECTED):
        text.append("● Connected", style="bold green")
    elif conn_state in (ConnectionState.SCANNING, ConnectionState.CONNECTING):
        text.append("◐ Connecting", style="bold yellow")
    elif conn_state == ConnectionState.ERROR:
        text.append("✗ Error", style="bold red")
    else:
        text.append("○ Disconnected", style="bold red")

    if conn_message:
        text.append(f" ({conn_message})", style="dim")

    text.append("    ", style="dim")

    if session_id is not None:
        text.append(f"Session #{session_id}", style="dim cyan")
    else:
        text.append("No active session", style="dim")

    text.append(f"    Msgs: {format_count(total_messages)}", style="dim")

    if truncated_count > 0:
        text.append(f"    ⚠ {truncated_count} truncated", style="dim yellow")

    return text


def render_sparkline(values: list[float], max_val: float | None = None) -> str:
    """Convert values to sparkline characters using 8-level gradient.

    Args:
        values: List of numeric values to plot.
        max_val: If provided, use as absolute max for consistent scaling.

    Returns:
        String of sparkline characters.
    """
    if not values:
        return ""

    effective_max = max_val if max_val is not None else max(values)
    if effective_max <= 0:
        return " " * len(values)

    result: list[str] = []
    for v in values:
        if v <= 0:
            result.append(" ")
        else:
            idx = int((v / effective_max) * 7) + 1
            result.append(SPARKLINE_CHARS[min(idx, 8)])

    return "".join(result)


def format_count(n: int) -> str:
    """Format large numbers with k/M suffixes."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    elif n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def _extract_sparkline_values(
    history: Iterable[tuple[datetime, float]],
    start: datetime,
    end: datetime,
    width: int,
) -> list[float]:
    """Extract time-bucketed values from a history deque for sparkline rendering.

    Args:
        history: Deque of (datetime, value) tuples.
        start: Start of the time window.
        end: End of the time window.
        width: Number of buckets (sparkline characters).

    Returns:
        List of averaged values per bucket.
    """
    if start >= end:
        return []

    total_seconds = (end - start).total_seconds()
    if total_seconds <= 0:
        return []

    bucket_seconds = total_seconds / width
    buckets: list[list[float]] = [[] for _ in range(width)]

    for timestamp, value in history:
        if timestamp < start or timestamp > end:
            continue
        bucket_idx = int((timestamp - start).total_seconds() / bucket_seconds)
        bucket_idx = min(bucket_idx, width - 1)
        buckets[bucket_idx].append(float(value))

    # Average each bucket, forward-fill empty buckets
    result: list[float] = []
    last_val = 0.0
    for bucket in buckets:
        if bucket:
            last_val = sum(bucket) / len(bucket)
        result.append(last_val)

    return result

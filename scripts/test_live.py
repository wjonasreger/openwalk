#!/usr/bin/env python3
"""Live test script for validating the protocol parser with real hardware.

This script connects to the InMovement Unsit treadmill via BLE and
validates that the protocol parser correctly handles real telemetry data.

Usage:
    uv run python scripts/test_live.py [--duration SECONDS]

Requirements:
    - Treadmill must be powered on
    - No other device (phone) connected to treadmill
    - Bluetooth permissions granted to terminal

Example:
    # Run for 60 seconds (default)
    uv run python scripts/test_live.py

    # Run for 5 minutes
    uv run python scripts/test_live.py --duration 300
"""

import asyncio
import sys
from datetime import datetime

import click
from bleak import BleakClient, BleakScanner
from rich.console import Console
from rich.live import Live
from rich.table import Table

# Add parent directory to path for imports
sys.path.insert(0, str(__file__).rsplit("/", 2)[0])

from openwalk.ble import DEVICE_NAME, NOTIFY_CHAR_UUID
from openwalk.protocol import (
    DataMessage,
    IdleMessage,
    SessionCounters,
    SpeedMessage,
    TruncatedFrame,
    parse_notification,
)

console = Console()


class LiveStats:
    """Track live statistics from treadmill data."""

    def __init__(self) -> None:
        self.counters = SessionCounters()
        self.message_count = 0
        self.data_count = 0
        self.speed_count = 0
        self.idle_count = 0
        self.truncated_count = 0
        self.last_message: str = ""
        self.last_data: DataMessage | None = None
        self.last_speed: int = 0
        self.start_time = datetime.now()

    def update(self, msg: DataMessage | SpeedMessage | IdleMessage | TruncatedFrame) -> None:
        """Update stats with a new message."""
        self.message_count += 1
        self.last_message = msg.raw_hex if hasattr(msg, "raw_hex") else ""

        if isinstance(msg, DataMessage):
            self.data_count += 1
            self.last_data = msg
            self.last_speed = msg.speed
            self.counters.update_steps(msg.steps)  # actual footstep counter (bytes 10-11 BE)
            self.counters.update_belt_revs(msg.belt_revs)
        elif isinstance(msg, SpeedMessage):
            self.speed_count += 1
            self.last_speed = msg.speed
        elif isinstance(msg, IdleMessage):
            self.idle_count += 1
        elif isinstance(msg, TruncatedFrame):
            self.truncated_count += 1

    def create_table(self) -> Table:
        """Create a Rich table with current stats."""
        elapsed = (datetime.now() - self.start_time).total_seconds()

        table = Table(title="OpenWalk Live Test", show_header=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        # Time and message counts
        table.add_row("Elapsed Time", f"{elapsed:.1f}s")
        table.add_row("Total Messages", str(self.message_count))
        table.add_row("DATA Messages", str(self.data_count))
        table.add_row("SPEED Messages", str(self.speed_count))
        table.add_row("IDLE Messages", str(self.idle_count))
        table.add_row("Truncated Frames", str(self.truncated_count))

        # Add separator
        table.add_row("---", "---")

        # Counter tracking
        table.add_row("Total Steps", str(self.counters.total_steps))
        table.add_row("Step Wraps", str(self.counters.steps.wrap_count))
        table.add_row("Total Belt Revs", str(self.counters.total_belt_revs))
        table.add_row("Belt Rev Wraps", str(self.counters.belt_revs.wrap_count))

        if self.counters.total_belt_revs > 0:
            table.add_row(
                "Steps/Revolution",
                f"{self.counters.steps_per_belt_rev:.2f}",
            )

        # Add separator
        table.add_row("---", "---")

        # Last DATA message details
        if self.last_data:
            table.add_row("Speed Setting", f"{self.last_speed}/20")
            table.add_row("Speed (mph)", f"{self.last_speed / 10:.1f}")
            table.add_row("Distance (raw)", str(self.last_data.distance_raw))
            table.add_row("Distance (mi)", f"{self.last_data.distance_miles:.2f}")
            table.add_row("Belt State", "Running" if self.last_data.is_belt_running else "Stopped")
            table.add_row("Belt Cadence", str(self.last_data.belt_cadence))
            table.add_row("Flag", str(self.last_data.flag))

        # Add separator
        table.add_row("---", "---")

        # Last raw message
        if self.last_message:
            # Truncate if too long
            hex_display = self.last_message[:48]
            if len(self.last_message) > 48:
                hex_display += "..."
            table.add_row("Last Frame (hex)", hex_display)

        # Error rate
        if self.message_count > 0:
            error_rate = (self.truncated_count / self.message_count) * 100
            table.add_row("Error Rate", f"{error_rate:.2f}%")

        return table


async def scan_for_treadmill() -> str | None:
    """Scan for the treadmill and return its address."""
    console.print(f"[cyan]Scanning for {DEVICE_NAME}...[/cyan]")

    device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=20.0)

    if device:
        console.print(f"[green]Found {DEVICE_NAME} at {device.address}[/green]")
        return device.address
    else:
        console.print(f"[red]Could not find {DEVICE_NAME}[/red]")
        console.print(
            "[yellow]Make sure the treadmill is powered on"
            " and no other device is connected.[/yellow]"
        )
        return None


async def run_live_test(duration: int) -> None:
    """Run the live test for the specified duration."""
    address = await scan_for_treadmill()
    if not address:
        return

    stats = LiveStats()

    def notification_handler(sender: int, data: bytes) -> None:
        """Handle BLE notifications."""
        messages = parse_notification(data)
        for msg in messages:
            stats.update(msg)

    console.print(f"[cyan]Connecting to {address}...[/cyan]")

    async with BleakClient(address) as client:
        console.print("[green]Connected![/green]")

        # Subscribe to notifications
        await client.start_notify(NOTIFY_CHAR_UUID, notification_handler)
        console.print(
            f"[green]Subscribed to notifications."
            f" Running for {duration} seconds...[/green]"
        )
        console.print("[yellow]Press Ctrl+C to stop early.[/yellow]\n")

        # Run with live display
        try:
            with Live(stats.create_table(), refresh_per_second=2, console=console) as live:
                for _ in range(duration * 2):  # Check every 0.5s
                    await asyncio.sleep(0.5)
                    live.update(stats.create_table())
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted by user[/yellow]")

        # Stop notifications
        await client.stop_notify(NOTIFY_CHAR_UUID)

    # Print final summary
    console.print("\n[bold green]Test Complete![/bold green]")
    console.print(stats.create_table())

    # Print validation results
    console.print("\n[bold]Validation Results:[/bold]")

    if stats.data_count > 0:
        console.print("[green]✓ DATA messages received and parsed[/green]")
    else:
        console.print("[yellow]⚠ No DATA messages received (was the belt running?)[/yellow]")

    if stats.speed_count > 0:
        console.print("[green]✓ SPEED messages received and parsed[/green]")
    else:
        console.print("[yellow]⚠ No SPEED messages received[/yellow]")

    if stats.idle_count > 0:
        console.print("[green]✓ IDLE messages received and parsed[/green]")
    else:
        console.print("[yellow]⚠ No IDLE messages received[/yellow]")

    if stats.counters.steps.has_wrapped:
        console.print("[green]✓ Step counter wrap-around detected and handled[/green]")
    else:
        console.print("[cyan]ℹ No step counter wrap-around (walk longer to test)[/cyan]")

    truncated_rate = (
        (stats.truncated_count / stats.message_count * 100)
        if stats.message_count > 0
        else 0
    )
    if truncated_rate < 2:
        console.print(
            f"[green]✓ Truncated frame rate:"
            f" {truncated_rate:.2f}% (expected <1%)[/green]"
        )
    else:
        console.print(
            f"[yellow]⚠ Truncated frame rate:"
            f" {truncated_rate:.2f}% (higher than expected)[/yellow]"
        )


@click.command()
@click.option("--duration", "-d", default=60, help="Test duration in seconds")
def main(duration: int) -> None:
    """Run live hardware test with the treadmill."""
    console.print("[bold]OpenWalk Live Hardware Test[/bold]")
    console.print("=" * 40)
    asyncio.run(run_live_test(duration))


if __name__ == "__main__":
    main()

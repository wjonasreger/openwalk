"""CLI entry point for OpenWalk."""

import asyncio
import csv
import json
import sys
from dataclasses import asdict
from typing import IO, Any

import click
from rich.console import Console
from rich.table import Table

from openwalk.config import (
    CONFIG_PATH,
    DEFAULT_CONFIG,
    format_config,
    load_config,
    save_config,
)


@click.group()
@click.version_option()
def cli() -> None:
    """OpenWalk - macOS terminal app for the InMovement Unsit treadmill."""
    pass


@cli.command()
@click.option("--debug", is_flag=True, help="Enable debug logging")
def run(debug: bool) -> None:
    """Start OpenWalk and connect to treadmill."""
    from openwalk.tui.app import run_app

    asyncio.run(run_app(debug=debug))


# ---------------------------------------------------------------------------
# history
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--limit", "-n", default=10, show_default=True, help="Number of sessions to show")
def history(limit: int) -> None:
    """List past walking sessions."""
    asyncio.run(_history(limit))


async def _history(limit: int) -> None:
    from openwalk.storage.database import Database
    from openwalk.storage.sessions import SessionManager

    console = Console()

    async with Database() as db:
        mgr = SessionManager(db)
        sessions = await mgr.get_recent_sessions(limit)

    if not sessions:
        console.print("[dim]No sessions recorded yet.[/dim]")
        return

    table = Table(title=f"Recent Sessions (last {len(sessions)})")
    table.add_column("ID", style="dim", justify="right")
    table.add_column("Date", style="cyan")
    table.add_column("Start", style="cyan")
    table.add_column("Duration", justify="right")
    table.add_column("Steps", justify="right")
    table.add_column("Distance", justify="right")
    table.add_column("Calories", justify="right")
    table.add_column("Avg Speed", justify="right")

    total_steps = 0
    total_distance = 0.0
    total_calories = 0

    for s in sessions:
        # Parse date/time from ISO format
        date_str = s.started_at[:10] if s.started_at else "—"
        time_str = s.started_at[11:16] if s.started_at and len(s.started_at) > 11 else "—"

        # Format duration
        secs = s.total_seconds or 0
        mins, sec = divmod(secs, 60)
        hrs, mins = divmod(mins, 60)
        duration = f"{hrs}:{mins:02d}:{sec:02d}" if hrs else f"{mins:02d}:{sec:02d}"

        steps = s.total_steps or 0
        dist = s.distance_miles or 0.0
        cals = s.calories or 0
        avg_spd = s.avg_speed or 0.0

        total_steps += steps
        total_distance += dist
        total_calories += cals

        table.add_row(
            str(s.id),
            date_str,
            time_str,
            duration,
            f"{steps:,}",
            f"{dist:.2f} mi",
            f"{cals} kcal",
            f"{avg_spd:.1f} mph",
        )

    # Summary row
    table.add_section()
    table.add_row(
        "",
        "",
        "",
        "Total",
        f"{total_steps:,}",
        f"{total_distance:.2f} mi",
        f"{total_calories} kcal",
        "",
        style="bold",
    )

    console.print(table)


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("session_id", type=int, required=False)
@click.option("--all", "export_all", is_flag=True, help="Export all sessions")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["csv", "json"]),
    default="csv",
    show_default=True,
    help="Output format",
)
@click.option(
    "--output", "-o", type=click.Path(), default=None, help="Output file (default: stdout)"
)
def export(session_id: int | None, export_all: bool, fmt: str, output: str | None) -> None:
    """Export session data to CSV or JSON.

    Provide a SESSION_ID to export a single session, or use --all.
    """
    if session_id is None and not export_all:
        raise click.UsageError("Provide a SESSION_ID or use --all")

    asyncio.run(_export(session_id, export_all, fmt, output))


async def _export(
    session_id: int | None, export_all: bool, fmt: str, output: str | None
) -> None:
    from openwalk.storage.database import Database
    from openwalk.storage.samples import SampleManager
    from openwalk.storage.sessions import SessionManager

    async with Database() as db:
        session_mgr = SessionManager(db)
        sample_mgr = SampleManager(db)

        if export_all:
            sessions = await session_mgr.get_recent_sessions(limit=10000)
        else:
            assert session_id is not None
            s = await session_mgr.get_session(session_id)
            if s is None:
                click.echo(f"Session {session_id} not found.", err=True)
                sys.exit(1)
            sessions = [s]

        if not sessions:
            click.echo("No sessions to export.", err=True)
            return

        # Gather all data
        export_data: list[dict[str, Any]] = []
        for s in sessions:
            samples = await sample_mgr.get_samples(s.id)
            export_data.append({
                "session": asdict(s),
                "samples": [asdict(sample) for sample in samples],
            })

    # Write output
    out: IO[str] = open(output, "w") if output else sys.stdout  # noqa: SIM115
    try:
        if fmt == "json":
            json.dump(export_data if export_all else export_data[0], out, indent=2)
            out.write("\n")
        else:
            _write_csv(export_data, out)
    finally:
        if output:
            out.close()

    if output:
        click.echo(f"Exported {len(sessions)} session(s) to {output}")


def _write_csv(export_data: list[dict[str, Any]], out_file: IO[str]) -> None:
    """Write session + sample data as CSV."""
    writer = csv.writer(out_file)

    for entry in export_data:
        session = entry["session"]
        samples = entry["samples"]

        # Session header
        writer.writerow(["# Session", session["id"]])
        writer.writerow([
            "# started_at", session["started_at"],
            "ended_at", session.get("ended_at", ""),
            "total_steps", session.get("total_steps", ""),
            "distance_miles", session.get("distance_miles", ""),
            "calories", session.get("calories", ""),
        ])

        # Sample rows
        if samples:
            sample_fields = [
                "captured_at", "steps", "distance_raw", "speed", "belt_state", "raw_hex",
            ]
            writer.writerow(sample_fields)
            for sample in samples:
                writer.writerow([sample.get(f, "") for f in sample_fields])

        writer.writerow([])  # blank line between sessions


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------


@cli.group()
def config() -> None:
    """Manage OpenWalk configuration."""
    pass


@config.command("show")
def config_show() -> None:
    """Display current configuration."""
    cfg = load_config()
    console = Console()
    console.print(f"[dim]Config file: {CONFIG_PATH}[/dim]")
    console.print(f"[dim]Exists: {CONFIG_PATH.exists()}[/dim]\n")
    console.print(format_config(cfg))


@config.command("init")
def config_init() -> None:
    """Create default configuration file."""
    if CONFIG_PATH.exists():
        click.confirm(f"{CONFIG_PATH} already exists. Overwrite?", abort=True)
    save_config(DEFAULT_CONFIG)
    click.echo(f"Created {CONFIG_PATH}")


if __name__ == "__main__":
    cli()

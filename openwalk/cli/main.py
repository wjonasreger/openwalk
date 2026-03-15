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
# sync
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--session", "-s", type=int, default=None, help="Sync a specific session ID")
@click.option("--retry", is_flag=True, help="Retry only failed syncs")
@click.option("--status", "show_status", is_flag=True, help="Show sync status of all sessions")
def sync(session: int | None, retry: bool, show_status: bool) -> None:
    """Sync walking sessions to Apple Health."""
    asyncio.run(_sync(session, retry, show_status))


async def _sync(session_id: int | None, retry: bool, show_status: bool) -> None:
    from openwalk.config import config_to_profile
    from openwalk.storage.chunks import ChunkManager
    from openwalk.storage.database import Database
    from openwalk.storage.samples import SampleManager
    from openwalk.storage.sessions import SessionManager, SessionRow, SessionState
    from openwalk.sync.healthkit_bridge import HealthKitBridge
    from openwalk.sync.sync_manager import SyncManager

    console = Console()

    async with Database() as db:
        session_mgr = SessionManager(db)
        sample_mgr = SampleManager(db)
        chunk_mgr = ChunkManager(db)

        # --status: show sync status table
        if show_status:
            sessions = await session_mgr.get_recent_sessions(limit=50)
            if not sessions:
                console.print("[dim]No sessions recorded yet.[/dim]")
                return

            table = Table(title="Session Sync Status")
            table.add_column("ID", style="dim", justify="right")
            table.add_column("Date", style="cyan")
            table.add_column("Steps", justify="right")
            table.add_column("Sync State")
            table.add_column("Error", style="dim")

            for s in sessions:
                date_str = s.started_at[:16] if s.started_at else "—"
                state = s.sync_state
                style = {
                    "SYNCED": "green",
                    "SYNC_FAILED": "red",
                    "SYNC_PENDING": "yellow",
                    "COMPLETED": "white",
                    "RECORDING": "cyan",
                }.get(state, "")
                error = (s.sync_last_error or "")[:50]
                table.add_row(
                    str(s.id),
                    date_str,
                    f"{s.total_steps or 0:,}",
                    f"[{style}]{state}[/{style}]",
                    error,
                )

            console.print(table)
            return

        # Check bridge availability
        cfg = load_config()
        bridge_path = cfg.get("healthkit", {}).get("bridge_path", "")
        bridge = HealthKitBridge(binary_path=bridge_path or None)

        if not bridge.available:
            console.print(
                "[red]HealthKit bridge not found.[/red]\n"
                "[dim]To install:[/dim]\n"
                "  cd openwalk-health-bridge && swift build -c release\n"
                "  cp .build/release/openwalk-health-bridge /usr/local/bin/"
            )
            return

        profile = config_to_profile(cfg)

        # Determine sessions to sync
        sessions_to_sync: list[SessionRow] = []
        if session_id is not None:
            found = await session_mgr.get_session(session_id)
            if found is None:
                console.print(f"[red]Session {session_id} not found.[/red]")
                return
            sessions_to_sync = [found]
        elif retry:
            sessions_to_sync = await session_mgr.get_sessions_by_state(
                SessionState.SYNC_FAILED
            )
        else:
            completed = await session_mgr.get_sessions_by_state(SessionState.COMPLETED)
            failed_sessions = await session_mgr.get_sessions_by_state(
                SessionState.SYNC_FAILED
            )
            sessions_to_sync = completed + failed_sessions

        if not sessions_to_sync:
            console.print("[dim]No sessions to sync.[/dim]")
            return

        console.print(f"Syncing {len(sessions_to_sync)} session(s)...\n")

        synced_count = 0
        failed_count = 0
        skipped_count = 0

        for s in sessions_to_sync:
            sync_mgr = SyncManager(
                session_mgr=session_mgr,
                chunk_mgr=chunk_mgr,
                bridge=bridge,
                sample_mgr=sample_mgr,
                profile=profile,
            )
            result = await sync_mgr.sync_existing_session(s.id)

            if result == "synced":
                console.print(f"  [green]✓[/green] Session {s.id}: synced")
                synced_count += 1
            elif result == "skipped":
                console.print(f"  [dim]–[/dim] Session {s.id}: already synced")
                skipped_count += 1
            else:
                error = sync_mgr.sync_error or "unknown error"
                console.print(f"  [red]✗[/red] Session {s.id}: {error}")
                failed_count += 1

        console.print(
            f"\n[bold]Done:[/bold] {synced_count} synced,"
            f" {failed_count} failed, {skipped_count} skipped"
        )


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

"""Main application loop — wires BLE, database, orchestrator, and Rich Live UI."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

from rich.console import Console
from rich.live import Live

from openwalk.ble.connection import ConnectionManager
from openwalk.config import config_to_profile, load_config
from openwalk.session.orchestrator import SessionOrchestrator
from openwalk.storage.database import Database
from openwalk.storage.samples import SampleManager
from openwalk.storage.sessions import SessionManager
from openwalk.tui.dashboard import render_dashboard
from openwalk.tui.keyboard import read_key

logger = logging.getLogger(__name__)


async def run_app(debug: bool = False) -> None:
    """Main application entry point.

    Wires ConnectionManager + Database + SessionOrchestrator + Rich Live.

    Args:
        debug: Enable debug logging.
    """
    if debug:
        logging.basicConfig(level=logging.DEBUG, format="%(name)s: %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING)

    console = Console()
    console.print("[bold cyan]OpenWalk[/bold cyan] starting...\n")

    async with Database() as db:
        session_mgr = SessionManager(db)
        sample_mgr = SampleManager(db)

        # Recover any interrupted sessions from a previous run
        await session_mgr.recover_interrupted()

        # Load config and create user profile
        config = load_config()
        profile = config_to_profile(config)

        orchestrator = SessionOrchestrator(session_mgr, sample_mgr, profile)

        # Create connection manager wired to orchestrator callbacks
        conn_mgr = ConnectionManager(
            on_data=orchestrator.handle_raw_data,
            on_state_change=orchestrator.handle_state_change,
        )

        # Start BLE connection as background task
        await conn_mgr.start_background()

        # Start DB queue processor as background task
        db_task = asyncio.create_task(orchestrator.process_db_queue())

        try:
            await _display_loop(console, orchestrator, conn_mgr)
        finally:
            # Graceful shutdown
            console.print("\n[dim]Shutting down...[/dim]")

            if orchestrator.state.session_id is not None:
                await orchestrator.end_session()

            orchestrator.stop()
            await conn_mgr.stop()
            db_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await db_task


async def _display_loop(
    console: Console,
    orchestrator: SessionOrchestrator,
    conn_mgr: ConnectionManager,
) -> None:
    """Run the Rich Live display loop with keyboard handling."""
    keyboard_task = asyncio.create_task(_keyboard_handler(orchestrator, conn_mgr))

    # Install signal handler for clean Ctrl+C
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _handle_signal() -> None:
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    try:
        with Live(
            render_dashboard(
                orchestrator.state,
                orchestrator.conn_state,
                orchestrator.conn_message,
                conn_mgr.router.total_notifications,
            ),
            console=console,
            refresh_per_second=2,
            screen=True,
        ) as live:
            while not stop_event.is_set():
                await asyncio.sleep(0.5)

                # Check session inactivity
                await orchestrator.check_inactivity()

                # Update display
                live.update(
                    render_dashboard(
                        orchestrator.state,
                        orchestrator.conn_state,
                        orchestrator.conn_message,
                        conn_mgr.router.total_notifications,
                    )
                )
    finally:
        keyboard_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await keyboard_task

        # Remove signal handlers
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)


async def _keyboard_handler(
    orchestrator: SessionOrchestrator,
    conn_mgr: ConnectionManager,
) -> None:
    """Handle keyboard input in a background task."""
    while True:
        try:
            key = await read_key()
        except asyncio.CancelledError:
            return
        except Exception:
            continue

        if key == "q":
            # Signal the display loop to stop
            raise asyncio.CancelledError
        elif key == "r":
            logger.info("Manual reconnect requested")
            await conn_mgr.stop()
            await conn_mgr.start_background()

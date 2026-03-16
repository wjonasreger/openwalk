"""Async keyboard input handler for terminal interaction."""

from __future__ import annotations

import asyncio
import select
import sys
import termios
import tty


async def read_key() -> str:
    """Read a single keypress asynchronously.

    Returns:
        The character pressed, or empty string on timeout.
    """
    return await asyncio.to_thread(_get_key)


def _get_key() -> str:
    """Read a single keypress with 0.5s timeout so the thread can exit cleanly."""
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        # Wait up to 0.5s for input; return empty string on timeout
        if select.select([sys.stdin], [], [], 0.5)[0]:
            return sys.stdin.read(1)
        return ""
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

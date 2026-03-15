"""Async keyboard input handler for terminal interaction."""

from __future__ import annotations

import asyncio
import sys
import termios
import tty


async def read_key() -> str:
    """Read a single keypress asynchronously.

    Returns:
        The character pressed.
    """
    return await asyncio.to_thread(_get_key)


def _get_key() -> str:
    """Blocking single-keypress read from stdin."""
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return ch

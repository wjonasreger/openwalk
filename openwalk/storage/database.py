"""Async SQLite database connection manager for OpenWalk.

Wraps aiosqlite with connection lifecycle management, WAL mode,
foreign key enforcement, and automatic schema migrations.

Usage:
    async with Database() as db:
        await db.execute("INSERT INTO sessions ...")
"""

import logging
from pathlib import Path
from types import TracebackType
from typing import Any

import aiosqlite

from openwalk.storage.schema import migrate_database

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path.home() / ".openwalk" / "openwalk.db"


class Database:
    """Async SQLite database with migrations and WAL mode.

    Args:
        db_path: Path to the SQLite database file.
            Use ":memory:" for in-memory databases (useful for testing).
            Defaults to ~/.openwalk/openwalk.db.
    """

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = str(db_path)
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Open database connection, configure pragmas, and run migrations."""
        if self._conn is not None:
            return

        # Create parent directory for file-based databases
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row

        # Enable foreign key constraints
        await self._conn.execute("PRAGMA foreign_keys = ON")

        # Enable WAL mode for better concurrent read/write performance
        await self._conn.execute("PRAGMA journal_mode = WAL")

        # Run schema migrations
        await migrate_database(self._conn)

        logger.info("Database connected: %s", self.db_path)

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
            logger.info("Database closed: %s", self.db_path)

    @property
    def conn(self) -> aiosqlite.Connection:
        """Get the active connection, raising if not connected."""
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn

    async def execute(self, sql: str, params: tuple[Any, ...] | list[Any] = ()) -> aiosqlite.Cursor:
        """Execute a SQL statement and commit."""
        cursor = await self.conn.execute(sql, params)
        await self.conn.commit()
        return cursor

    async def executemany(self, sql: str, params_list: list[tuple[Any, ...] | list[Any]]) -> None:
        """Execute a SQL statement with multiple parameter sets and commit."""
        await self.conn.executemany(sql, params_list)
        await self.conn.commit()

    async def fetchone(
        self, sql: str, params: tuple[Any, ...] | list[Any] = ()
    ) -> aiosqlite.Row | None:
        """Execute a query and return the first row."""
        async with self.conn.execute(sql, params) as cursor:
            return await cursor.fetchone()

    async def fetchall(
        self, sql: str, params: tuple[Any, ...] | list[Any] = ()
    ) -> list[aiosqlite.Row]:
        """Execute a query and return all rows."""
        async with self.conn.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
            return list(rows)

    # Context manager support

    async def __aenter__(self) -> "Database":
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()

"""SQLite storage layer for OpenWalk sessions, samples, and sync chunks.

Public API:

    Database — Async SQLite connection manager with migrations
    SessionManager — Session CRUD and state machine
    SampleManager — Sample insertion and queries
    ChunkManager — Sync chunk CRUD for HealthKit incremental sync
    SessionState — Session lifecycle states enum
    SessionRow — Typed session query result
    SampleRow — Typed sample query result
    ChunkRow — Typed sync chunk query result

Usage:
    async with Database() as db:
        sessions = SessionManager(db)
        samples = SampleManager(db)
        chunks = ChunkManager(db)

        session_id = await sessions.create_session()
        await samples.insert_sample(session_id, data_msg)
        await sessions.finalize_session(session_id)
"""

from openwalk.storage.chunks import ChunkManager, ChunkRow
from openwalk.storage.database import Database
from openwalk.storage.samples import SampleManager, SampleRow
from openwalk.storage.sessions import SessionManager, SessionRow, SessionState

__all__ = [
    "ChunkManager",
    "ChunkRow",
    "Database",
    "SampleManager",
    "SampleRow",
    "SessionManager",
    "SessionRow",
    "SessionState",
]

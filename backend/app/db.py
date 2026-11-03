"""Async SQLAlchemy engine, session helpers and shared column types.

Writes go through :meth:`Database.write`, which serializes write transactions inside the process
with an ``asyncio.Lock``. SQLite allows one writer at a time; serializing in-process avoids
``database is locked`` errors when concurrent requests and background evaluations write at once.
Reads use :meth:`Database.read` and run concurrently (WAL mode).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import DateTime, event, text
from sqlalchemy.engine import Dialect, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    """Current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


def new_id() -> str:
    """A new 32-character lowercase hex identifier."""
    return uuid.uuid4().hex


class UTCDateTime(TypeDecorator[datetime]):
    """Stores naive UTC datetimes and returns timezone-aware UTC datetimes."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


def _ensure_parent_dir(database: str) -> None:
    Path(database).expanduser().parent.mkdir(parents=True, exist_ok=True)


def _casefold(value: Any) -> Any:
    """SQL ``casefold(text)``: Unicode case folding (SQLite's ``lower()`` only folds ASCII)."""
    return value.casefold() if isinstance(value, str) else value


def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
    # Case-insensitive search folds both sides with the same Unicode-aware function.
    dbapi_connection.create_function("casefold", 1, _casefold, deterministic=True)
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
    finally:
        cursor.close()


class Database:
    """Owns the engine and session factory for one application instance."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.engine: AsyncEngine = create_async_engine(url)
        if self.engine.dialect.name == "sqlite":
            event.listen(self.engine.sync_engine, "connect", _sqlite_pragmas)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)
        self._write_lock = asyncio.Lock()

    async def init(self) -> None:
        """Create the database file's directory and all tables."""
        from app.models import Base  # local import: models import this module

        parsed = make_url(self.url)
        if parsed.get_backend_name() == "sqlite" and parsed.database not in {None, "", ":memory:"}:
            await asyncio.to_thread(_ensure_parent_dir, str(parsed.database))
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    @asynccontextmanager
    async def read(self) -> AsyncIterator[AsyncSession]:
        """A session for read-only work."""
        async with self.sessionmaker() as session:
            yield session

    @asynccontextmanager
    async def write(self) -> AsyncIterator[AsyncSession]:
        """A session inside a transaction that commits on success and rolls back on error."""
        async with self._write_lock, self.sessionmaker() as session, session.begin():
            yield session

    async def ping(self) -> bool:
        """Whether a trivial query succeeds."""
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:  # readiness reports any failure as "error"
            return False
        return True

    async def dispose(self) -> None:
        await self.engine.dispose()

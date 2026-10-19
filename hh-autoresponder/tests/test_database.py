import os
import tempfile

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.mark.asyncio
async def test_sqlite_pragmas_applied_on_connect():
    """Проверяет, что при подключении к SQLite выставляются WAL, synchronous=NORMAL и busy_timeout=30000."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        connect_args = {
            "check_same_thread": False,
            "timeout": 30,
        }
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}", connect_args=connect_args)

        @event.listens_for(engine.sync_engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA busy_timeout=30000;")
            cursor.close()

        session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with session_maker() as session:
            journal_mode = (await session.execute(text("PRAGMA journal_mode;"))).scalar()
            busy_timeout = (await session.execute(text("PRAGMA busy_timeout;"))).scalar()
            synchronous = (await session.execute(text("PRAGMA synchronous;"))).scalar()

        assert journal_mode.lower() == "wal"
        assert busy_timeout == 30000
        assert synchronous == 1  # 1 == NORMAL

        await engine.dispose()
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

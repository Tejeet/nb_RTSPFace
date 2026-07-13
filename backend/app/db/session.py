"""Engine and session factory for SQLite (WAL mode, multi-thread safe)."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base


def create_db_engine(sqlite_path: Path) -> Engine:
    """Create the SQLite engine with pragmas suited to an edge device."""
    engine = create_engine(
        f"sqlite:///{sqlite_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
        pool_pre_ping=True,
    )

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_conn, _record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    return engine


class DatabaseManager:
    """Owns the engine and hands out short-lived sessions."""

    def __init__(self, sqlite_path: Path) -> None:
        self._engine = create_db_engine(sqlite_path)
        self._session_factory = sessionmaker(bind=self._engine, expire_on_commit=False)

    def create_schema(self) -> None:
        """Create all tables if they do not exist."""
        Base.metadata.create_all(self._engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Yield a session; commit on success, rollback on error."""
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        """Close all pooled connections."""
        self._engine.dispose()

"""Engine and session factory for SQLite (WAL mode, multi-thread safe)."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base

# Columns added after the initial release: (table, column, DDL type).
# create_all() only creates missing tables, so existing databases get these
# via lightweight ALTERs at startup (idempotent).
_SCHEMA_ADDITIONS: tuple[tuple[str, str, str], ...] = (
    ("faces", "frame_path", "TEXT"),
)


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
        """Create all tables if they do not exist and apply column additions."""
        Base.metadata.create_all(self._engine)
        with self._engine.connect() as conn:
            for table, column, ddl_type in _SCHEMA_ADDITIONS:
                existing = {
                    row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))
                }
                if column not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))
                    conn.commit()

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

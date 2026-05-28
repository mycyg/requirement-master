from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(
    settings.database_url,
    echo=False,
    future=True,
    # `pool_pre_ping` is a no-op for SQLite (always reuses the same file) but
    # rescues against silent stale connections if a future deployment swaps
    # to Postgres/MySQL.
    pool_pre_ping=True,
    connect_args=connect_args,
)


if settings.database_url.startswith("sqlite"):
    # WAL + busy_timeout — without these, the single-writer SQLite default
    # produces `database is locked` errors under realistic concurrent
    # polling (Dashboard fans out 7 reads every 6s; reminders poll
    # everywhere every 60s). WAL lets readers proceed while a writer is
    # mid-transaction; busy_timeout makes writers wait up to 5s for the
    # lock instead of failing instantly with SQLITE_BUSY. Foreign keys
    # ON because the schema relies on FK constraints for cascade cleanup.
    @event.listens_for(engine, "connect")
    def _configure_sqlite(dbapi_conn, _conn_record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        try:
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.execute("PRAGMA foreign_keys=ON")
        finally:
            cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

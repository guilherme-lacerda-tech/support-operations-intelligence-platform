from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from support_operations_intelligence_platform.core.settings import get_settings
from support_operations_intelligence_platform.core.migrations import run_migrations
from support_operations_intelligence_platform.models import Base


def build_engine(database_url: str | None = None):
    settings = get_settings()
    url = database_url or settings.database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    kwargs = {"connect_args": connect_args}
    if url == "sqlite:///:memory:":
        kwargs["poolclass"] = StaticPool
    engine = create_engine(url, future=True, **kwargs)
    if url.startswith("sqlite") and settings.sqlite_mode == "wal":
        @event.listens_for(engine, "connect")
        def set_sqlite_pragmas(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA temp_store=MEMORY")
            cursor.close()
    elif url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def set_sqlite_busy_timeout(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

    return engine


def create_session_factory(database_url: str | None = None) -> sessionmaker[Session]:
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)
    run_migrations(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


SessionLocal = create_session_factory()


@contextmanager
def session_scope(factory: sessionmaker[Session] = SessionLocal) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

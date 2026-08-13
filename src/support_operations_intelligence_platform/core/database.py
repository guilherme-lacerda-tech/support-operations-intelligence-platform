from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from support_operations_intelligence_platform.core.settings import get_settings
from support_operations_intelligence_platform.models import Base


def build_engine(database_url: str | None = None):
    url = database_url or get_settings().database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    kwargs = {"connect_args": connect_args}
    if url == "sqlite:///:memory:":
        kwargs["poolclass"] = StaticPool
    return create_engine(url, future=True, **kwargs)


def create_session_factory(database_url: str | None = None) -> sessionmaker[Session]:
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)
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


"""Engine and session setup.

`make_session_factory(url)` is used directly by tests and evals (each gets
its own throwaway database). The API and worker share one process-wide
factory via `configure()` / `session_scope()`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from store.models import Base


def make_session_factory(url: str) -> sessionmaker[Session]:
    kwargs: dict = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 15}
        if url in ("sqlite://", "sqlite:///:memory:"):
            kwargs["poolclass"] = StaticPool  # one shared in-memory connection
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")  # API and worker read/write concurrently
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


_factory: sessionmaker[Session] | None = None
_factory_url: str | None = None


def configure(url: str) -> sessionmaker[Session]:
    """(Re)create the process-wide session factory for `url`."""
    global _factory, _factory_url
    if _factory is None or _factory_url != url:
        _factory, _factory_url = make_session_factory(url), url
    return _factory


def get_factory() -> sessionmaker[Session]:
    if _factory is None:
        from settings import get_settings

        configure(get_settings().database_url)
    assert _factory is not None
    return _factory


@contextmanager
def session_scope() -> Iterator[Session]:
    """A session that commits on success and rolls back on error."""
    session = get_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from price_matcher.config import get_settings

_engine = None
_SessionFactory: sessionmaker | None = None


def _bootstrap() -> None:
    global _engine, _SessionFactory
    if _engine is not None:
        return
    settings = get_settings()
    _engine = create_engine(settings.database_url, future=True, pool_pre_ping=True)
    _SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)


def get_engine():
    _bootstrap()
    return _engine


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context-managed DB session. Commits on success, rolls back on error."""
    _bootstrap()
    assert _SessionFactory is not None
    session = _SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

"""Shared test fixtures."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app import models  # noqa: F401  (register tables on Base.metadata)


@pytest.fixture
def sqlite_session(monkeypatch):
    """Fresh in-memory SQLite session per test.

    StaticPool is required here: the FastAPI TestClient (used by the `client`
    fixture) runs requests on a background thread, and plain :memory: SQLite
    hands each thread its own empty database unless every connection is
    forced through the same shared connection.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    # The analytics middleware runs outside the request dependency and opens its
    # own session; point that at this in-memory database too, so a test run can
    # never write page views into the real data/jobscout.db.
    import app.db as db_module

    monkeypatch.setattr(db_module, "new_session", Session)

    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def client(sqlite_session):
    """TestClient for the real FastAPI app, wired to an isolated in-memory DB
    (never touches the project's real data/jobscout.db)."""
    from fastapi.testclient import TestClient

    from app.db import get_session
    from app.main import app

    app.dependency_overrides[get_session] = lambda: sqlite_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()

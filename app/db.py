"""SQLite database setup via SQLAlchemy."""
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import DB_PATH


class Base(DeclarativeBase):
    pass


engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

# Columns added after initial release -> (table, column, SQLite type) for auto-migration.
_ADDED_COLUMNS: list[tuple[str, str, str]] = [
    ("candidates", "gap_analysis_json", "TEXT DEFAULT '[]'"),
    ("candidates", "last_summary_json", "TEXT DEFAULT '{}'"),
    ("candidates", "skill_experience_json", "TEXT DEFAULT '{}'"),
    ("candidates", "preferences_json", "TEXT DEFAULT '{}'"),
    ("candidates", "public_id", "TEXT"),
    ("matches", "notified_at", "DATETIME"),
    ("jobs", "source_detail", "TEXT DEFAULT ''"),
]


def _migrate() -> None:
    """Add any newly-introduced columns to existing SQLite tables in place."""
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table, column, coltype in _ADDED_COLUMNS:
            if table not in existing_tables:
                continue
            cols = {c["name"] for c in insp.get_columns(table)}
            if column not in cols:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}"))

        if "candidates" in existing_tables:
            cols = {c["name"] for c in insp.get_columns("candidates")}
            if "public_id" in cols:
                # backfill any pre-existing rows created before public_id existed
                from app.models import new_public_id

                rows = conn.execute(text("SELECT id FROM candidates WHERE public_id IS NULL OR public_id = ''")).fetchall()
                for (cid,) in rows:
                    conn.execute(text("UPDATE candidates SET public_id = :pid WHERE id = :cid"),
                                {"pid": new_public_id(), "cid": cid})
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_candidates_public_id ON candidates (public_id)"))


def init_db() -> None:
    # Import models so their tables are registered on Base.metadata
    from app import models  # noqa: F401

    Base.metadata.create_all(engine)
    _migrate()


def get_session():
    """FastAPI dependency yielding a DB session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def new_session():
    """A standalone session for code that runs outside the request dependency
    (the analytics middleware). Kept as an indirection so tests can point it at
    their in-memory database instead of the real one."""
    return SessionLocal()

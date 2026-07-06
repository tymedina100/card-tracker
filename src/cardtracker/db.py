"""Database engine creation and session helpers."""

from pathlib import Path

from sqlalchemy import inspect
from sqlmodel import Session, SQLModel, create_engine

from cardtracker import models  # noqa: F401  ensures all tables are registered
from cardtracker.config import Settings


def get_engine(settings: Settings, echo: bool = False):
    if settings.database_url:
        # Hosted Postgres (Railway). URL scheme is already normalized to psycopg.
        return create_engine(settings.database_url, echo=echo, pool_pre_ping=True)
    db_path = Path(settings.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{db_path}", echo=echo)


def init_db(engine) -> None:
    SQLModel.metadata.create_all(engine)
    _add_missing_columns(engine)


def _add_missing_columns(engine) -> None:
    """Lightweight forward migration: when a model gains a column, add it to an
    existing database instead of requiring a rebuild. Dialect-agnostic via the
    SQLAlchemy inspector, so it works on both SQLite and Postgres."""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.connect() as conn:
        for table in SQLModel.metadata.tables.values():
            if table.name not in existing_tables:
                continue
            existing = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                ddl = (f"ALTER TABLE {table.name} ADD COLUMN {column.name} "
                       f"{column.type.compile(engine.dialect)}")
                default = getattr(column.default, "arg", None)
                if default is not None and not callable(default):
                    ddl += f" DEFAULT {default!r}"
                conn.exec_driver_sql(ddl)
        conn.commit()


def get_session(engine) -> Session:
    return Session(engine)

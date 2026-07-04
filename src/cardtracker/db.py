"""Database engine creation and session helpers."""

from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from cardtracker import models  # noqa: F401  ensures all tables are registered
from cardtracker.config import Settings


def get_engine(settings: Settings, echo: bool = False):
    db_path = Path(settings.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{db_path}", echo=echo)


def init_db(engine) -> None:
    SQLModel.metadata.create_all(engine)
    _add_missing_columns(engine)


def _add_missing_columns(engine) -> None:
    """Lightweight forward migration: when a model gains a column, add it to an
    existing SQLite database instead of requiring a rebuild."""
    with engine.connect() as conn:
        for table in SQLModel.metadata.tables.values():
            rows = conn.exec_driver_sql(f"PRAGMA table_info('{table.name}')").fetchall()
            existing = {row[1] for row in rows}
            if not existing:
                continue
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

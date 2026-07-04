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


def get_session(engine) -> Session:
    return Session(engine)

from datetime import date

import pytest
from sqlmodel import Session, SQLModel, create_engine

from cardtracker.config import Settings
from cardtracker.models import Card, Category, Grader


@pytest.fixture
def engine():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture
def sample_card(session) -> Card:
    card = Card(
        category=Category.POKEMON,
        player_or_character="Charizard",
        set_name="Base Set",
        year=1999,
        card_number="4",
        grader=Grader.PSA,
        grade="9",
    )
    session.add(card)
    session.commit()
    session.refresh(card)
    return card


@pytest.fixture
def settings_with_creds() -> Settings:
    return Settings(ebay_client_id="test-id", ebay_client_secret="test-secret")


@pytest.fixture
def sold_csv(tmp_path):
    def _write(content: str):
        path = tmp_path / "solds.csv"
        path.write_text(content, encoding="utf-8")
        return path
    return _write


VALID_CSV = """card_id,sold_date,price,shipping,currency,title,condition,listing_url
1,2026-06-28,415.00,4.99,USD,Charizard PSA 9,Graded,https://ebay.com/itm/123
1,2026-06-30,432.50,0,USD,Charizard Base Set PSA 9,Graded,
"""

SAMPLE_DATE = date(2026, 6, 28)

"""Sold-comp import from CSV files exported from Terapeak or assembled manually.

Expected CSV schema (header row required, column order does not matter):

    card_id, sold_date, price, shipping, currency, title, condition, listing_url

Required per row: sold_date (YYYY-MM-DD) and price (positive number).
card_id may be omitted from the file when the import command supplies one.
shipping defaults to 0, currency defaults to USD, the rest default to empty.
"""

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from cardtracker.models import CompSourceName, PriceType
from cardtracker.sources.base import CompRecord, CompSource

REQUIRED_COLUMNS = {"sold_date", "price"}
KNOWN_COLUMNS = REQUIRED_COLUMNS | {
    "card_id", "shipping", "currency", "title", "condition", "listing_url",
}


class CsvImportError(ValueError):
    pass


@dataclass
class CsvRow:
    """A validated row: the comp record plus which card it belongs to."""

    card_id: int
    record: CompRecord


class CsvImportSource(CompSource):
    """Confirmed sales imported from a local CSV file."""

    source_name = CompSourceName.CSV
    price_type = PriceType.SOLD

    def __init__(self, path: str | Path, default_card_id: int | None = None,
                 skip_bad_rows: bool = False) -> None:
        self._path = Path(path)
        self._default_card_id = default_card_id
        self._skip_bad_rows = skip_bad_rows
        self.skipped: list[str] = []

    def fetch_comps(self, query: str = "", limit: int = 0) -> list[CompRecord]:
        return [row.record for row in self.read_rows()]

    def read_rows(self) -> list[CsvRow]:
        """Parse and validate the file. Raises CsvImportError on the first bad row
        unless skip_bad_rows is set, in which case bad rows land in self.skipped."""
        if not self._path.exists():
            raise CsvImportError(f"CSV file not found: {self._path}")
        with open(self._path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                raise CsvImportError(f"{self._path} is empty")
            columns = {c.strip().lower() for c in reader.fieldnames}
            missing = REQUIRED_COLUMNS - columns
            if missing:
                raise CsvImportError(
                    f"Missing required column(s): {', '.join(sorted(missing))}. "
                    f"Expected schema: {', '.join(sorted(KNOWN_COLUMNS))}"
                )
            if "card_id" not in columns and self._default_card_id is None:
                raise CsvImportError(
                    "No card_id column in the file and no --card-id given on import"
                )
            rows: list[CsvRow] = []
            self.skipped = []
            for line_num, raw in enumerate(reader, start=2):
                cleaned = {(k or "").strip().lower(): (v or "").strip()
                           for k, v in raw.items()}
                try:
                    rows.append(self._parse_row(cleaned, line_num))
                except CsvImportError as exc:
                    if self._skip_bad_rows:
                        self.skipped.append(str(exc))
                    else:
                        raise
            return rows

    def _parse_row(self, row: dict[str, str], line_num: int) -> CsvRow:
        def fail(message: str) -> CsvImportError:
            return CsvImportError(f"line {line_num}: {message}")

        card_id_text = row.get("card_id", "")
        if card_id_text:
            try:
                card_id = int(card_id_text)
            except ValueError:
                raise fail(f"card_id '{card_id_text}' is not an integer") from None
        elif self._default_card_id is not None:
            card_id = self._default_card_id
        else:
            raise fail("card_id is empty and no --card-id was given")

        try:
            price = float(row.get("price", ""))
        except ValueError:
            raise fail(f"price '{row.get('price', '')}' is not a number") from None
        if price <= 0:
            raise fail(f"price must be positive, got {price}")

        try:
            sold_date = date.fromisoformat(row.get("sold_date", ""))
        except ValueError:
            raise fail(
                f"sold_date '{row.get('sold_date', '')}' is not a valid YYYY-MM-DD date"
            ) from None

        shipping_text = row.get("shipping", "")
        if shipping_text:
            try:
                shipping = float(shipping_text)
            except ValueError:
                raise fail(f"shipping '{shipping_text}' is not a number") from None
            if shipping < 0:
                raise fail(f"shipping must not be negative, got {shipping}")
        else:
            shipping = 0.0

        return CsvRow(
            card_id=card_id,
            record=CompRecord(
                price=price,
                observed_date=sold_date,
                shipping=shipping,
                currency=row.get("currency", "") or "USD",
                listing_url=row.get("listing_url", ""),
                title_raw=row.get("title", ""),
                condition_raw=row.get("condition", ""),
            ),
        )

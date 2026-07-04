# cardtracker

Local price comp tracker and value predictor for sports and Pokemon cards.
Runs entirely on your machine: SQLite database, no paid infrastructure.

## Status

Phase 0: scaffolding and ingestion. Cards, comps from the eBay Browse API
(active listings) and from sold-comp CSV imports.

## Setup

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env
# then edit .env and add your eBay keys (optional, CSV import works without them)
```

## Where comp data comes from

eBay retired the old Finding API that returned sold listings, and the
Marketplace Insights API that replaced it is gated to approved partners.
So cardtracker uses three source adapters:

| Source | Price type | Availability |
| --- | --- | --- |
| Browse API | ask (active listings) | Standard developer keys |
| CSV import | sold (confirmed sales) | Always, from Terapeak exports or manual entry |
| Marketplace Insights | sold | Stubbed, enable with INSIGHTS_ENABLED=true if approved |

Every comp row stores its source and whether it is an ask or a sold price.
Analysis never mixes the two without labeling.

## CLI usage

```powershell
cardtracker init-db
cardtracker add-card --category pokemon --player "Charizard" --set "Base Set" --year 1999 --number 4 --grader PSA --grade 9
cardtracker list-cards
cardtracker pull-comps 1 --query "1999 pokemon base set charizard psa 9" --limit 50
cardtracker import-csv sold_comps.csv --card-id 1
```

## Sold-comp CSV schema

Header row required. Column order does not matter. Extra columns are ignored.

| Column | Required | Format |
| --- | --- | --- |
| sold_date | yes | YYYY-MM-DD |
| price | yes | positive number, no currency symbol |
| card_id | no if --card-id given | integer id from list-cards |
| shipping | no | number, defaults to 0 |
| currency | no | defaults to USD |
| title | no | raw listing title |
| condition | no | raw condition text |
| listing_url | no | link to the sold listing |

Example:

```csv
card_id,sold_date,price,shipping,currency,title,condition,listing_url
1,2026-06-28,415.00,4.99,USD,1999 Pokemon Base Set Charizard 4/102 PSA 9,Graded,https://ebay.com/itm/123
1,2026-06-30,432.50,0,USD,Charizard Base Set Holo PSA 9 MINT,Graded,
```

Invalid rows abort the import with a line number. Pass --skip-bad-rows to
import the good rows and report the bad ones instead.

## Tests and linting

```powershell
pytest
ruff check
```

Tests never hit the live eBay API. All HTTP calls are mocked.

## Secrets

Keys live in .env, which is gitignored. Never commit .env.

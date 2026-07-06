# cardtracker

Price comp tracker and value predictor for sports and Pokemon cards. Runs
locally against SQLite for a single user, or hosted on Railway with Postgres
and Google sign-in so many people can each keep a private collection.

## Status

Complete. Cards, comp ingestion (Browse API asks, CSV solds), rolling
market stats with scheduled refresh, an explainable comparable-cohort
prediction engine with backtesting, the full money toolkit (cost basis,
net-after-fees calculator, unrealized and realized P&L, deal analyzer with
max buy price, inventory status, price targets), and a Streamlit dashboard
with popular-value dropdowns, per-account data isolation, and Google sign-in.

## Dashboard

```powershell
cardtracker dashboard
```

The dashboard is fully interactive: every feature works through forms and
buttons, no CLI required. Eight views in the sidebar:

- Portfolio: total cost basis, market value of holdings, unrealized P&L
  (net of fees), realized P&L, plus holdings and sales tables.
- Cards: every card with comp counts and status, plus the add-card form.
- Card detail: price history chart (ask vs sold, with 30 day median
  lines), the full stat line, the live prediction with its rationale, the
  position summary, and action tabs to log a buy, log a sell (with
  optional fee estimation), set status/quantity/listed price and targets,
  and pull active eBay asks.
- Movers: every card's prediction at a chosen horizon, up and down columns
  sorted by confidence, rationale in each row.
- Deals: active asks under the max buy price for a target ROI, with links.
- Calculators: the net-after-fees breakdown and the max buy price
  calculator, both live as you type.
- Data: drag-and-drop CSV import for sold comps (stats auto-refresh),
  refresh-all-stats and score-predictions buttons, and the CSV format
  reference.
- Accuracy: backtest hit rate, per-direction accuracy, and the cumulative
  hit rate over time.

Browsing never writes: predictions shown on pages are not logged unless
you click the log button, and viewing a card does not create rows. The
CLI still exists and does everything the dashboard does, for scripting
and scheduled refreshes.

## Deploying to Railway (multi-user, durable)

Hosted on Railway the app has durable Postgres storage and Google sign-in, so
each visitor signs in and sees only their own collection. Data survives
redeploys and app restarts.

1. Push this repository to GitHub.
2. In Railway, create a project from the repo, then add a Postgres plugin.
   Railway injects `DATABASE_URL` into the app service automatically; the app
   rewrites the URL to use the psycopg 3 driver and creates its tables on
   first boot.
3. Create a Google OAuth client at
   https://console.cloud.google.com > APIs & Services > Credentials > OAuth
   client ID (type: Web application). Add
   `https://YOUR-APP.up.railway.app/oauth2callback` as an authorized redirect
   URI. Copy the client id and secret.
4. Set these variables on the Railway app service (Variables tab):
   - `AUTH_REDIRECT_URI` = `https://YOUR-APP.up.railway.app/oauth2callback`
   - `AUTH_COOKIE_SECRET` = any long random string
     (`python -c "import secrets;print(secrets.token_hex(32))"`)
   - `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` from step 3
   - Optionally `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET` for live Browse pulls.
5. Railway starts the app from the `Procfile`
   (`streamlit run streamlit_app.py --server.port $PORT ...`). Open the URL and
   sign in with Google.

Auth secrets are written to `.streamlit/secrets.toml` at startup from those
variables and are never committed. If the four `AUTH_*`/`GOOGLE_*` variables are
not all set, the app runs in open local single-owner mode (no login screen),
which is what you get running locally.

The old Streamlit Community Cloud path still works for a throwaway demo, but its
free tier has ephemeral storage and one shared database, so use Railway for a
real deployment.

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
cardtracker refresh-stats
cardtracker stats 1
cardtracker schedule-refresh --interval-hours 12
cardtracker predict 1 --horizon-days 30
cardtracker backtest --horizon-days 30 --step-days 7
cardtracker score-predictions
cardtracker log-buy 1 --price 380 --shipping 12.50 --taxes 31.35 --date 2026-05-02
cardtracker cost-basis
cardtracker net 450 --shipping-charged 5 --tax 30 --shipping-cost 6 --promoted 2
cardtracker unrealized --shipping-cost 5
cardtracker log-sell 1 --price 470 --estimate-fees --shipping-cost 5
cardtracker realized
cardtracker max-buy 1 --target-roi 30
cardtracker deals --target-roi 30 --days 14
cardtracker set-status 1 --status listed --listed-price 475
cardtracker inventory --status listed
cardtracker set-targets 1 --target 500 --min 440
cardtracker targets
```

## Money features

- net: itemized net proceeds after the fee model (final value fee on the
  full buyer payment including shipping and tax, per-order fee, optional
  promoted and processing). Sales tax raises fees but never reaches the
  seller.
- unrealized: per held card, market stat (30 day sold median, ask median
  flagged as fallback) minus fees minus cost basis, with ROI and totals.
- log-sell / realized: actual sale price and fees against average buy cost
  per copy, realized P&L across all sales.
- max-buy / deals: work backward from market through fees to the most you
  can pay and still hit a target ROI or profit; recent asks below that
  price are flagged as deals.
- set-status / inventory: owned, listed, sold, or watching with quantity,
  cost, listed price, and market side by side.
- set-targets / targets: target sell and min accept prices judged against
  the market with a per-card verdict.

## Cost basis

log-buy records one copy per run with the full cost breakdown: price, fees,
shipping, taxes, and grading cost. cost-basis shows the per-card totals and
the average cost per copy owned. Inventory quantity, status, and acquired
date stay in sync automatically. Adding new columns to the schema is handled
in place; existing databases are migrated without losing data.

## Market stats

refresh-stats computes one price snapshot per card per price type (ask and
sold are always separate) covering: rolling medians (7, 30, 90 day), 30 day
mean, counts, low, high, spread, volatility, velocity (per week), and linear
trend slope over 30 and 90 days. All stats use the delivered price, item
price plus shipping. Rerunning on the same day replaces that day's rows.
schedule-refresh keeps snapshots fresh on an interval until stopped with
Ctrl+C.

## Predictions

predict builds a cohort of comparable cards (same player or character, set,
and year, grade within 1 point, same or base parallel), measures 30 day
momentum for the card and its cohort from sold comps (ask prices only as a
flagged fallback), and combines them (60 percent own trend, 40 percent
cohort median) into a direction, a confidence score, and a written rationale
naming the cards and numbers behind it. Predictions are logged.

backtest replays history: it predicts at past dates using only the comps
known at each date, then scores each call against the sold median that
followed. score-predictions fills in outcomes for logged live predictions
once their horizon has elapsed. Realized outcomes always come from sold
prices, never asks.

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

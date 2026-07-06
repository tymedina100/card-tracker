# Card Tracker Product Roadmap

## Platform Direction

Streamlit is the right short-term surface for the first website because it keeps
the product moving: one Python codebase, fast dashboard iteration, and direct
reuse of the valuation, fee, prediction, and import logic that already exists.
It is not the best long-term foundation for mobile or desktop. Native camera
search, push alerts, offline-friendly workflows, shared API clients, and a
polished public web app all want a stable service boundary instead of a
Streamlit rerun-driven UI.

Recommended path:

1. Keep Streamlit as the internal/prototype web app while the product model is
   still changing.
2. Extract the app's business operations behind an API-shaped service layer.
3. Add FastAPI for auth, cards, inventory, transactions, comps, alerts, saved
   searches, exports, and predictions.
4. Build the public web app in React/Next against the API.
5. Build mobile in Expo/React Native against the same API, starting with camera
   search, show-floor deal grading, watchlist alerts, and collection lookup.
6. Add desktop later only if there is a real need for local-first collection
   management, bulk import/export, or show preparation.

## Competitive Gap Matrix

| Area | Card Ladder public capability | Current Card Tracker state | Priority |
| --- | --- | --- | --- |
| Sales database | Large historical sales database across many platforms | eBay asks via Browse API and user-imported sold CSVs | High |
| Collection tracking | Collection values, CSV bulk upload, daily estimates | Collection, cost basis, imports, manual values | High |
| Watchlist alerts | Threshold alerts via web, email, and mobile | Watching status and deal math, no notifications | High |
| Advanced search | Query tools, synonyms, typo handling, cert search, filters | Basic eBay query and local table filters | High |
| Camera search | Native camera search and graded-cert/image matching | Manual Scan page with pricing brain only | High for mobile |
| Population reports | PSA/BGS/SGC/CGC pop reports and growth | Not built | Medium |
| Showcase sharing | Public collection links | Not built | Medium |
| Compare | Card and index comparisons | Not built | Medium |
| Indexes | Player/category/custom market indexes | Cohort predictions and movers, no explicit indexes | Medium |
| Feed/news | Hobby news and daily sales recap | Not built | Low |

## Product Differentiators

Card Tracker should lean into decision support instead of trying to become a
Card Ladder clone immediately. The strongest current differentiators are:

- Fee-aware net proceeds and profit math.
- Max-buy and deal analyzer workflows.
- Buy, hold, list, sell, or pass recommendations.
- Manual market overrides for cards without reliable comps.
- Realized and unrealized P&L.
- Explainable forecasts and backtesting.

The near-term product promise should be: know what you paid, what you could net,
what to do next, and what price makes a deal worth taking.

## Near-Term Feature Priorities

1. Category-aware card entry, cleaner filters, and safer imports.
2. Watchlist price alerts with email first, push notifications later.
3. Saved searches for deal hunting, including max price, platform, grade, and
   category filters.
4. Shareable showcase links with per-collection privacy controls.
5. Card compare: side-by-side market value, cost basis, ROI, liquidity, trend,
   and confidence.
6. Camera-search MVP for mobile: take photo, extract cert if visible, otherwise
   search likely card names and let the user confirm.
7. Indexes built from the user's own collection first, then broader market
   indexes only when data rights are clear.

## Do Not Build Yet

- A proprietary global sales database without clear data licensing.
- Population-report ingestion until provider terms and refresh limits are known.
- Push notifications before an API and account notification preferences exist.
- A desktop app before the web and mobile API contracts stabilize.
- Fully automated valuation claims that cannot explain their data source,
  freshness, and confidence.

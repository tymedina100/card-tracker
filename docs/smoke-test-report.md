# Smoke Test Report

## Test Summary

- Date tested: 2026-07-06
- Environment tested: Current deployed Railway app availability check plus local
  Streamlit app on Windows, launched from the repo virtualenv. Full interactive
  deployed browser testing was not possible from this Codex environment.
- App URL: https://card-tracker-production-7fd2.up.railway.app/
- Legacy Streamlit URL checked from prompt: https://card-trackerr.streamlit.app/
- Local URL checked: http://localhost:8501
- Tester: Codex
- Source checklist: `docs/demo-checklist.md`
- Result: Local smoke test passed. Deployed app still needs Tyler to manually
  verify in a clean browser session.

## Environment Notes

- The Linear issue now identifies the Railway URL above as the current demo
  link and the Streamlit Community Cloud URL as the older demo.
- A read-only HTTP check of the current Railway URL returned HTTP 200 and the
  Streamlit app shell.
- The old Streamlit URL from the prompt could not be reached from the sandboxed
  shell without further browser support.
- The in-app browser connection was blocked by local AppData permissions before
  it could complete an interactive deployed smoke test.
- Per the fallback instructions, the app was run locally with
  `.\.venv\Scripts\cardtracker.exe dashboard`.
- The local dashboard responded with HTTP 200 on `http://localhost:8501`.

## Commands Run

```bash
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\cardtracker.exe dashboard
```

Results:

- `pytest`: 192 passed in 10.21s
- `ruff`: All checks passed
- Railway app check: current demo URL returned HTTP 200
- `cardtracker dashboard`: local Streamlit server responded with HTTP 200

## Checklist Results

| Checklist area | Status | Result |
| --- | --- | --- |
| First-run experience | Deployed availability pass / local flow pass / needs deployed interaction | The current Railway URL returned HTTP 200. Local app opened in single-owner mode and showed Portfolio metrics and empty-state structure. Tyler still needs to verify the deployed clean-browser and Google sign-in path. |
| Adding a card | Pass | Required-field validation appeared, then a sample Pokemon card saved and appeared in the Cards table. |
| Editing card details/status | Pass | Card notes updated, buy logging worked, status/targets/manual market values saved, and invalid min-above-target validation displayed an error. |
| Importing data | Pass locally | A sample sold-comp CSV row imported through the repo import path, stats refreshed, and the Data page import/backup sections rendered. The deployed upload flow should still be checked manually. |
| Viewing portfolio/value data | Pass | Portfolio metrics and Today's Actions rendered after adding cost and manual market data. |
| Checking deals or price/value logic | Pass | Deals analyzer and Calculators showed net proceeds, expected profit, max buy, and related metrics from sample values. |
| Exporting or reviewing data | Pass locally | Data page Backup section rendered with sample collection data; existing dashboard coverage verifies export control presence. Deployed download behavior should still be manually checked. |

## Bugs Or Confusing Moments Found

- No user-facing app defects were found during the local smoke test.
- Current Railway app availability was confirmed with HTTP 200, but deployed app
  interaction could not be verified from this environment, so deployed readiness
  is not fully confirmed.
- The local Streamlit test harness emitted non-blocking dataframe serialization
  warnings while rendering mixed-value tables. The app recovered automatically,
  the existing tests pass, and no user-facing failure was observed.

No separate Linear bug issues were created because no actionable user-facing
bug was confirmed. If Tyler sees a deployed sign-in, upload, or download
problem during manual verification, create a focused follow-up issue from that
specific failure.

## Screenshots Needed

- No screenshots were captured in this environment.
- Tyler should capture screenshots only if the deployed manual check shows a
  sign-in, upload, export, or recommendation display problem.

## Recommended Next Actions

1. Tyler should open https://card-tracker-production-7fd2.up.railway.app/ in a
   clean browser or incognito session.
2. Verify Google sign-in or the expected deployed first-run behavior.
3. Run the same `docs/demo-checklist.md` flow with one sample card on the
   deployed app.
4. Confirm CSV upload and CSV download behavior on the deployed app.
5. If deployed verification passes, schedule 3-5 real-user tests with
   collectors and capture feedback using the checklist questions.

## Ready For 3-5 Real-User Tests?

Conditionally yes. The local app passed the full practical smoke path, and the
automated suite is green. The deployed app should be considered ready for
3-5 real-user tests after Tyler manually verifies clean-browser access, CSV
upload, and CSV download on
https://card-tracker-production-7fd2.up.railway.app/.

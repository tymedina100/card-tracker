# Real-User Demo Checklist

Use this checklist when Tyler and Blake sit with a real collector and ask them
to try Card Tracker. The goal is not to teach every feature. The goal is to see
whether a collector can understand the core workflow: add a card, track what it
cost, estimate what it is worth, and decide what to do next.

## Session Setup

- Tester:
- Date:
- Device/browser:
- Test environment:
- Collector type:
- Notes before starting:

Before the session, tell the tester:

- Use a real card if you are comfortable, or use a sample card you know well.
- Think out loud while you use the app.
- There are no wrong answers; confusing moments are the point of the test.
- Do not enter private credentials, payment data, or anything you do not want
  stored in the demo environment.

## First-Run Experience

| Step | Tester action | Expected result | Notes |
| --- | --- | --- | --- |
| 1 | Open Card Tracker. | The app loads without an error. If Google sign-in is enabled, the tester sees a clear sign-in screen. If running locally, the dashboard opens directly. | |
| 2 | Look at the sidebar navigation. | The tester can identify the main areas: Portfolio, Scan, Cards, Card detail, Movers, Deals, Calculators, Data, and Accuracy. | |
| 3 | Start from the empty or current Portfolio view. | The page explains that there are no held cards yet, or shows current portfolio totals and action buckets. | |
| 4 | Describe what they think the product helps them do. | Tyler can tell whether the value proposition is clear without extra explanation. | |

## Add A Card

| Step | Tester action | Expected result | Notes |
| --- | --- | --- | --- |
| 1 | Go to Cards. | The Cards page shows an add-card area and any existing card rows. | |
| 2 | Add a card with category, player or character, set name, year, card number, parallel, grader, grade, cert number, and notes where available. | The card saves successfully and appears in the Cards table. | |
| 3 | Leave a required field blank, if the tester is willing. | The app explains what is required instead of saving bad data or crashing. | |
| 4 | Use filters or search to find the new card. | The tester can find the card again without help. | |

## Edit Card Details And Status

| Step | Tester action | Expected result | Notes |
| --- | --- | --- | --- |
| 1 | Go to Card detail and choose the new card. | The card detail page loads the selected card. If there are no comps yet, it says so clearly. | |
| 2 | Open the edit section and change a detail such as notes, grade, or card number. | The app saves the change and shows a confirmation. | |
| 3 | In Status and targets, set status, quantity, listed price, target sell price, min accept price, target ROI, and manual market inputs as appropriate. | The app saves the values and updates the position summary. | |
| 4 | Try a realistic market value and cost basis. | The Position Summary shows cost, market value, net if sold, profit, ROI, recommendation, and reason. | |
| 5 | If the tester enters a min accept price above target sell price, observe the result. | The app warns that min accept is above target and does not silently save an invalid setup. | |

## Import Data

| Step | Tester action | Expected result | Notes |
| --- | --- | --- | --- |
| 1 | Go to Data. | The tester sees import, maintenance, backup, and reset areas. | |
| 2 | Review the sold-comp CSV format example. | The tester understands the required columns: sold_date and price, plus optional card_id, shipping, currency, title, condition, and listing_url. | |
| 3 | Import a small sold-comp CSV for the card, or discuss whether the tester knows where they would get that file. | Valid rows import, stats refresh, and any errors name the row or missing card clearly. | |
| 4 | Try the cards CSV import if testing a bulk collection workflow. | Valid card rows import, skipped rows are explained, and no private files are required. | |

## View Portfolio And Value Data

| Step | Tester action | Expected result | Notes |
| --- | --- | --- | --- |
| 1 | Go to Portfolio. | Headline metrics show total cost basis, market value of holdings, unrealized P&L, and realized P&L. | |
| 2 | Review Today's Actions. | The tester sees buckets for sell candidates, underwater cards, deals under max buy, stale inventory, listed cards, and missing market value. | |
| 3 | Open relevant action buckets. | The tester can connect the recommendation to the card's price, cost, ROI, and status. | |
| 4 | Review holdings and realized sales tables. | The tester can tell what is owned, what has sold, and where profit or loss comes from. | |

## Check Deals And Price/Value Logic

| Step | Tester action | Expected result | Notes |
| --- | --- | --- | --- |
| 1 | Go to Deals. | The manual deal analyzer is available even if automatic comps are empty. | |
| 2 | Enter an asking price, estimated market value, target ROI, and exit assumptions. | The app shows net if sold at market, expected profit, max buy, come-down amount, and a BUY, NEGOTIATE, or PASS verdict. | |
| 3 | Change the asking price above and below max buy. | The verdict changes in a way the tester can explain. | |
| 4 | Go to Calculators and try Net after fees or Max buy price. | The math feels consistent with the Deals and Card detail recommendations. | |
| 5 | Ask the tester whether the recommendation is trustworthy. | Tyler captures whether the explanation, data source, and confidence are enough for a real buying or selling decision. | |

## Export Or Review Data

| Step | Tester action | Expected result | Notes |
| --- | --- | --- | --- |
| 1 | Go to Data, then Backup: export and import. | Export controls are visible when there is data to export. | |
| 2 | Export portfolio CSV. | The download includes card, status, quantity, cost, market, net, profit, ROI, target ROI, needed sale price, and recommendation. | |
| 3 | Download cards backup. | The backup includes the card catalog fields needed to re-import cards later. | |
| 4 | Review the reset warning without deleting data. | The tester understands that reset is destructive and requires confirmation. | |

## Observer Notes

Capture these during the session:

- Where did the tester pause, ask for help, or reread labels?
- Which page did they expect to use first?
- Which fields did they understand immediately?
- Which fields needed explanation?
- Did the tester trust manual values, imported comps, or neither?
- Did the tester understand the difference between ask prices and sold prices?
- Did the tester understand net proceeds after fees?
- Did the tester see the app as a collection tracker, a deal tool, or both?
- What would Tyler or Blake need to explain before showing this to another
  collector?

## Feedback Questions

Ask these at the end and write down the tester's words as closely as possible:

1. What confused you?
2. What felt useful?
3. What would make you use this again?
4. What felt missing or annoying?
5. Would you trust the price/value recommendation? Why or why not?

## Ready For The Next Test?

After the session, Tyler and Blake should decide:

- Is the first-run path clear enough for another collector?
- Can a collector add and update a card without guided help?
- Does the app produce at least one useful recommendation from the tester's
  own card data?
- Are import/export expectations clear enough for a non-technical collector?
- Are any bugs or confusing moments serious enough to file as separate Linear
  issues before the next demo?

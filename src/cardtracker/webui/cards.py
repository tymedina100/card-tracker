"""Cards list with add form, and the card detail page with all actions."""

from collections import defaultdict
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sqlmodel import select

from cardtracker.ebay_auth import MissingCredentialsError
from cardtracker.models import (
    Card,
    Category,
    Comp,
    Grader,
    Inventory,
    InventoryStatus,
    PriceSnapshot,
    describe_card,
)
from cardtracker.portfolio import (
    avg_cost_per_copy,
    cost_basis_summary,
    delete_card,
    get_or_create_inventory,
    log_buy,
    log_sell,
    set_status,
    set_targets,
    unrealized_summary,
)
from cardtracker.predict import predict_card
from cardtracker.reference import (
    GRADES,
    PARALLELS,
    POKEMON_SETS,
    POPULAR_CHARACTERS,
    POPULAR_PLAYERS,
    SPORTS_SETS,
)
from cardtracker.sources import BrowseApiSource, save_comps
from cardtracker.stats import latest_snapshots, refresh_snapshots
from cardtracker.webui.shared import (
    ASK_COLOR,
    SOLD_COLOR,
    card_label,
    card_picker,
    combo,
    current_owner,
    distinct_values,
    fee_model,
    flash_and_rerun,
    get_settings,
    money,
    open_session,
    show_flash,
    style_chart,
)


def cards_page() -> None:
    show_flash()
    st.title("🗂️ Cards")
    owner = current_owner()
    with open_session() as session:
        cards = session.exec(
            select(Card).where(Card.owner == owner).order_by(Card.id)
        ).all()
        card_ids = [card.id for card in cards]
        comp_rows = (session.exec(
            select(Comp.card_id, Comp.price_type)
            .where(Comp.card_id.in_(card_ids))
        ).all() if card_ids else [])
        inventories = {
            inv.card_id: inv for inv in session.exec(
                select(Inventory).where(Inventory.owner == owner)
            ).all()
        }
        used_players = distinct_values(session, Card.player_or_character, owner)
        used_sets = distinct_values(session, Card.set_name, owner)
        used_parallels = distinct_values(session, Card.variation_or_parallel, owner)
        used_grades = distinct_values(session, Card.grade, owner)
    counts: dict[tuple[int, str], int] = defaultdict(int)
    for card_id, price_type in comp_rows:
        counts[(card_id, str(price_type))] += 1

    with st.expander("➕ Add a card", expanded=not cards):
        with st.form("add_card", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            category = c1.selectbox("Category", [c.value for c in Category],
                                    key="add_category")
            with c2:
                player = combo("Player or character",
                               POPULAR_CHARACTERS + POPULAR_PLAYERS,
                               used_players, key="add_player")
            with c3:
                set_name = combo("Set name", POKEMON_SETS + SPORTS_SETS,
                                 used_sets, key="add_set")
            c4, c5, c6 = st.columns(3)
            year = c4.number_input("Year", 1900, 2100, 2024, key="add_year")
            number = c5.text_input("Card number", key="add_number")
            with c6:
                parallel = combo("Variation or parallel", PARALLELS,
                                 used_parallels, key="add_parallel")
            c7, c8, c9 = st.columns(3)
            grader = c7.selectbox("Grader", [g.value for g in Grader],
                                  index=len(Grader) - 1, key="add_grader")
            with c8:
                grade = combo("Grade", GRADES, used_grades, key="add_grade",
                              help="For raw cards leave blank.")
            cert = c9.text_input("Cert number", key="add_cert")
            notes = st.text_input("Notes", key="add_notes")
            if st.form_submit_button("Add card", type="primary"):
                if not player.strip() or not set_name.strip():
                    st.error("Player/character and set name are required.")
                else:
                    card = Card(
                        owner=owner,
                        category=Category(category),
                        player_or_character=player.strip(),
                        set_name=set_name.strip(),
                        year=int(year),
                        card_number=number.strip(),
                        variation_or_parallel=parallel.strip(),
                        grader=Grader(grader),
                        grade=grade.strip(),
                        cert_number=cert.strip() or None,
                        notes=notes.strip(),
                    )
                    with open_session() as session:
                        session.add(card)
                        session.commit()
                        session.refresh(card)
                    flash_and_rerun(f"Added card {card_label(card)}")

    if not cards:
        st.info("No cards yet. Add your first one above. A PSA 10 and a PSA 9 "
                "of the same card are two separate cards.")
        return

    f1, f2 = st.columns(2)
    set_filter = f1.selectbox("Filter by set", ["All sets", *used_sets],
                              key="cards_filter_set")
    player_filter = f2.selectbox("Filter by player or character",
                                 ["All players", *used_players],
                                 key="cards_filter_player")
    visible = [
        card for card in cards
        if (set_filter == "All sets" or card.set_name == set_filter)
        and (player_filter == "All players"
             or card.player_or_character == player_filter)
    ]
    if not visible:
        st.caption("No cards match the current filters.")
        return

    rows = []
    for card in visible:
        inventory = inventories.get(card.id)
        rows.append({
            "id": card.id,
            "card": describe_card(card),
            "category": str(card.category),
            "status": str(inventory.status) if inventory else "",
            "qty": inventory.quantity if inventory else 0,
            "asks": counts[(card.id, "ask")],
            "solds": counts[(card.id, "sold")],
        })
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    st.caption("Open the Card detail view to see charts, predictions, and "
               "to log buys and sells.")


def _price_history_chart(comps: list[Comp],
                         snapshot_history: list[PriceSnapshot]) -> go.Figure:
    df = pd.DataFrame({
        "date": [c.sold_date_or_seen_date for c in comps],
        "delivered": [c.price + c.shipping for c in comps],
        "type": [str(c.price_type) for c in comps],
        "title": [c.title_raw for c in comps],
    })
    fig = go.Figure()
    colors = {"sold": SOLD_COLOR, "ask": ASK_COLOR}
    for price_type in ("sold", "ask"):
        sub = df[df["type"] == price_type]
        if not sub.empty:
            fig.add_trace(go.Scatter(
                x=sub["date"], y=sub["delivered"], mode="markers",
                name=f"{price_type} comps", text=sub["title"],
                marker={"color": colors[price_type], "size": 9,
                        "line": {"width": 1, "color": "#0e1521"}},
            ))
    history = pd.DataFrame({
        "date": [s.as_of_date for s in snapshot_history],
        "median_30d": [s.median_30d for s in snapshot_history],
        "type": [str(s.price_type) for s in snapshot_history],
    }).dropna()
    for price_type in ("sold", "ask"):
        sub = history[history["type"] == price_type]
        if len(sub) > 1:
            fig.add_trace(go.Scatter(
                x=sub["date"], y=sub["median_30d"], mode="lines",
                name=f"{price_type} 30d median",
                line={"color": colors[price_type], "dash": "dot", "width": 2},
            ))
    fig.update_layout(yaxis_title="delivered price")
    style_chart(fig)
    return fig


def card_detail_page() -> None:
    show_flash()
    st.title("🔎 Card detail")
    owner = current_owner()
    with open_session() as session:
        card = card_picker(session, owner, key="detail_card")
        if card is None:
            st.info("No cards yet. Add one in the Cards view first.")
            return
        comps = session.exec(select(Comp).where(Comp.card_id == card.id)).all()
        snapshots = latest_snapshots(session, card.id)
        snapshot_history = session.exec(
            select(PriceSnapshot).where(PriceSnapshot.card_id == card.id)
            .order_by(PriceSnapshot.as_of_date)
        ).all()
        prediction = predict_card(session, card.id, log=False)
        basis = cost_basis_summary(session, owner=owner, card_id=card.id)
        holdings = [line for line in unrealized_summary(session, fee_model(),
                                                        owner=owner)
                    if line.card.id == card.id]
        # viewing must not write rows; a pending Inventory still renders defaults
        inventory = get_or_create_inventory(session, card.id, owner=owner)

    st.subheader("Price history: ask vs sold")
    if comps:
        st.plotly_chart(_price_history_chart(comps, snapshot_history),
                        width="stretch")
    else:
        st.info("No comps yet. Import a sold CSV in the Data view or pull "
                "asks in the Actions section below.")

    left, right = st.columns(2)
    with left, st.container(border=True):
        st.subheader("Stat line")
        if snapshots:
            fields = ["as_of_date", "median_7d", "median_30d", "median_90d",
                      "mean_30d", "sale_count_30d", "sale_count_90d", "low_30d",
                      "high_30d", "spread_30d", "volatility_30d", "velocity_30d",
                      "trend_slope_30d", "trend_slope_90d"]
            table = {price_type: {f: getattr(snap, f) for f in fields}
                     for price_type, snap in snapshots.items()}
            st.dataframe(pd.DataFrame(table), width="stretch")
        else:
            st.info("No snapshots yet. Use Refresh all stats in the Data view.")

    with right:
        with st.container(border=True):
            st.subheader("Prediction")
            direction = str(prediction.direction)
            badge = {"up": ":green[▲ UP]", "down": ":red[▼ DOWN]",
                     "flat": ":gray[► FLAT]"}[direction]
            st.markdown(f"### {badge}")
            st.caption(f"{prediction.horizon_days} day horizon, confidence "
                       f"{prediction.confidence:.2f}, expected move "
                       f"{prediction.expected_move_pct:+.1f}%")
            st.write(prediction.rationale)
            if st.button("📌 Log this prediction for scoring", key="log_prediction"):
                with open_session() as session:
                    predict_card(session, card.id, log=True)
                flash_and_rerun("Prediction logged. Score it from the Data view "
                                "once its horizon has passed.")

        with st.container(border=True):
            st.subheader("Position")
            per_copy = basis[0].cost_per_copy if basis else None
            profit = holdings[0].profit if holdings else None
            roi = holdings[0].roi_pct if holdings else None
            rows = {
                "status": str(inventory.status),
                "quantity": inventory.quantity,
                "cost basis": money(inventory.cost_basis),
                "cost per copy": money(per_copy),
                "profit if sold now": money(profit) if profit is not None else "n/a",
                "ROI if sold now": f"{roi:+.1f}%" if roi is not None else "n/a",
                "listed price": money(inventory.listed_price),
                "target sell": money(inventory.target_sell_price),
                "min accept": money(inventory.min_accept_price),
            }
            st.dataframe(pd.DataFrame(rows.items(), columns=["", "value"]),
                         width="stretch", hide_index=True)

    st.subheader("Actions")
    buy_tab, sell_tab, status_tab, pull_tab = st.tabs(
        ["🛒 Log buy", "💵 Log sell", "📦 Status and targets", "🛰️ Pull eBay asks"])

    with buy_tab, st.form("log_buy", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        price = c1.number_input("Purchase price", 0.0, step=1.0, format="%.2f",
                                key="buy_price")
        buy_date = c2.date_input("Date", value=date.today(), key="buy_date")
        platform = c3.text_input("Platform", key="buy_platform")
        c4, c5, c6, c7 = st.columns(4)
        fees = c4.number_input("Fees", 0.0, step=0.5, format="%.2f", key="buy_fees")
        shipping = c5.number_input("Shipping", 0.0, step=0.5, format="%.2f",
                                   key="buy_shipping")
        taxes = c6.number_input("Taxes", 0.0, step=0.5, format="%.2f",
                                key="buy_taxes")
        grading = c7.number_input("Grading cost", 0.0, step=0.5, format="%.2f",
                                  key="buy_grading")
        notes = st.text_input("Notes", key="buy_notes")
        if st.form_submit_button("Log buy", type="primary"):
            if price <= 0:
                st.error("Purchase price must be above zero.")
            else:
                with open_session() as session:
                    transaction = log_buy(session, card.id, price,
                                          buy_date=buy_date, fees=fees,
                                          shipping=shipping, taxes=taxes,
                                          grading=grading, platform=platform,
                                          notes=notes, owner=owner)
                flash_and_rerun(f"Logged buy of one copy for a total cost of "
                                f"{money(transaction.total_cost)}.")

    with sell_tab, st.form("log_sell", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        sale_price = c1.number_input("Sale price", 0.0, step=1.0, format="%.2f",
                                     key="sell_price")
        sell_date = c2.date_input("Date", value=date.today(), key="sell_date")
        sell_platform = c3.text_input("Platform", key="sell_platform")
        c4, c5, c6 = st.columns(3)
        sale_fees = c4.number_input("Actual fees", 0.0, step=0.5, format="%.2f",
                                    key="sell_fees")
        estimate = c5.checkbox("Estimate fees from fee model instead",
                               key="sell_estimate")
        ship_cost = c6.number_input("Shipping cost", 0.0, step=0.5, format="%.2f",
                                    key="sell_shipping")
        if st.form_submit_button("Log sell", type="primary"):
            if sale_price <= 0:
                st.error("Sale price must be above zero.")
            else:
                if estimate:
                    from cardtracker.fees import compute_net

                    sale_fees = compute_net(fee_model(), sale_price).total_fees
                with open_session() as session:
                    log_sell(session, card.id, sale_price, sell_date=sell_date,
                             fees=sale_fees, shipping_cost=ship_cost,
                             platform=sell_platform, owner=owner)
                    cost = avg_cost_per_copy(session, card.id, owner=owner)
                net = sale_price - sale_fees - ship_cost
                message = (f"Logged sell: net {money(net)} after fees "
                           f"{money(sale_fees)}.")
                if cost:
                    profit = net - cost
                    message += (f" Realized profit vs avg cost {money(cost)}: "
                                f"{profit:+,.2f} ({profit / cost * 100:+.1f}%).")
                flash_and_rerun(message)

    with status_tab, st.form("status_targets"):
        c1, c2, c3 = st.columns(3)
        statuses = [s.value for s in InventoryStatus]
        status = c1.selectbox("Status", statuses,
                              index=statuses.index(str(inventory.status)),
                              key="status_value")
        quantity = c2.number_input("Quantity", 0, 999, inventory.quantity,
                                   key="status_qty")
        listed = c3.number_input("Listed price (0 = not listed)", 0.0,
                                 value=inventory.listed_price or 0.0, step=1.0,
                                 format="%.2f", key="status_listed")
        c4, c5 = st.columns(2)
        target = c4.number_input("Target sell price (0 = unset)", 0.0,
                                 value=inventory.target_sell_price or 0.0,
                                 step=1.0, format="%.2f", key="target_price")
        min_accept = c5.number_input("Min accept price (0 = unset)", 0.0,
                                     value=inventory.min_accept_price or 0.0,
                                     step=1.0, format="%.2f", key="min_price")
        if st.form_submit_button("Save", type="primary"):
            if target and min_accept and min_accept > target:
                st.error("Min accept price is above the target sell price.")
            else:
                with open_session() as session:
                    set_status(session, card.id,
                               status=InventoryStatus(status),
                               quantity=int(quantity),
                               listed_price=listed or None, owner=owner)
                    set_targets(session, card.id,
                                target_sell_price=target or None,
                                min_accept_price=min_accept or None, owner=owner)
                flash_and_rerun("Status and targets saved.")

    with pull_tab, st.form("pull_comps"):
        query = st.text_input("eBay search terms", value=describe_card(card),
                              key="pull_query")
        limit = st.slider("Max listings", 10, 200, 50, key="pull_limit")
        if st.form_submit_button("Pull active listings", type="primary"):
            settings = get_settings()
            try:
                source = BrowseApiSource(settings)
                records = source.fetch_comps(query, limit=limit)
                with open_session() as session:
                    saved = save_comps(session, card.id, source, records)
                    refresh_snapshots(session, card_id=card.id, owner=owner)
                flash_and_rerun(f"Saved {len(saved)} ask comps and refreshed "
                                f"stats ({settings.ebay_env}).")
            except MissingCredentialsError as exc:
                st.warning(str(exc))
            except Exception as exc:  # noqa: BLE001 surface eBay errors in the UI
                st.error(f"eBay request failed: {exc}")

    with st.expander("✏️ Edit or delete this card"):
        with st.form("edit_card"):
            categories = [c.value for c in Category]
            graders = [g.value for g in Grader]
            e1, e2, e3 = st.columns(3)
            e_category = e1.selectbox("Category", categories,
                                      index=categories.index(str(card.category)),
                                      key="edit_category")
            e_player = e2.text_input("Player or character",
                                     value=card.player_or_character, key="edit_player")
            e_set = e3.text_input("Set name", value=card.set_name, key="edit_set")
            e4, e5, e6 = st.columns(3)
            e_year = e4.number_input("Year", 1900, 2100, card.year, key="edit_year")
            e_number = e5.text_input("Card number", value=card.card_number,
                                     key="edit_number")
            e_parallel = e6.text_input("Variation or parallel",
                                       value=card.variation_or_parallel,
                                       key="edit_parallel")
            e7, e8, e9 = st.columns(3)
            e_grader = e7.selectbox("Grader", graders,
                                    index=graders.index(str(card.grader)),
                                    key="edit_grader")
            e_grade = e8.text_input("Grade", value=card.grade, key="edit_grade")
            e_cert = e9.text_input("Cert number", value=card.cert_number or "",
                                   key="edit_cert")
            e_notes = st.text_input("Notes", value=card.notes, key="edit_notes")
            if st.form_submit_button("Save changes", type="primary"):
                if not e_player.strip() or not e_set.strip():
                    st.error("Player/character and set name are required.")
                else:
                    with open_session() as session:
                        db_card = session.get(Card, card.id)
                        if db_card is not None and db_card.owner == owner:
                            db_card.category = Category(e_category)
                            db_card.player_or_character = e_player.strip()
                            db_card.set_name = e_set.strip()
                            db_card.year = int(e_year)
                            db_card.card_number = e_number.strip()
                            db_card.variation_or_parallel = e_parallel.strip()
                            db_card.grader = Grader(e_grader)
                            db_card.grade = e_grade.strip()
                            db_card.cert_number = e_cert.strip() or None
                            db_card.notes = e_notes.strip()
                            session.add(db_card)
                            session.commit()
                    flash_and_rerun("Card updated.")

        st.divider()
        st.caption("Deleting removes this card and all of its comps, stats, buys, "
                   "sells, and predictions. This cannot be undone.")
        confirm = st.checkbox("I understand, delete this card", key="delete_confirm")
        if st.button("🗑️ Delete card", disabled=not confirm, key="delete_card_btn"):
            with open_session() as session:
                delete_card(session, card.id, owner=owner)
            flash_and_rerun("Card deleted.")

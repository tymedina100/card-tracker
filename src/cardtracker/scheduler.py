"""Scheduled snapshot refresh using APScheduler."""

import logging
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler

from cardtracker.config import load_settings
from cardtracker.db import get_engine, get_session, init_db
from cardtracker.stats import refresh_snapshots

logger = logging.getLogger(__name__)


def refresh_job() -> int:
    """One refresh run with its own session. Returns snapshots written."""
    settings = load_settings()
    engine = get_engine(settings)
    init_db(engine)
    with get_session(engine) as session:
        written = refresh_snapshots(session)
    logger.info("Wrote %d snapshots at %s", len(written), datetime.now().isoformat())
    return len(written)


def run_scheduler(interval_hours: float, run_immediately: bool = True) -> None:
    """Blocking scheduler that refreshes snapshots on an interval. Ctrl+C stops it."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if run_immediately:
        refresh_job()
    scheduler = BlockingScheduler()
    scheduler.add_job(refresh_job, "interval", hours=interval_hours, id="refresh_snapshots")
    logger.info("Scheduler started, refreshing every %s hour(s). Ctrl+C to stop.",
                interval_hours)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")

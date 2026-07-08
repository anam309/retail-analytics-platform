"""
etl/run.py — CLI entrypoint for the full ETL pipeline.

Usage:
    python -m etl.run
    DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/db python -m etl.run
    BATCH_DATE=2024-03-15 python -m etl.run
"""

import logging
import sys

import pandas as pd
from sqlalchemy import create_engine

from config.settings import (
    BATCH_DATE,
    DQ_THRESHOLDS,
    GIT_SHA,
    LOG_DIR,
    SOURCE_FILES,
    TRIGGERED_BY,
    DB_URL,
)
from etl.extract import extract
from etl.load import run_pipeline
from etl.transform import transform_customers, transform_products, transform_sales

log = logging.getLogger(__name__)


def configure_logging() -> None:
    log_file = LOG_DIR / f"etl_{BATCH_DATE.isoformat()}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s %(name)s  %(message)s",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(log_file)],
    )


def main() -> None:
    configure_logging()
    log.info("[run] Starting retail ETL - batch_date=%s triggered_by=%s", BATCH_DATE, TRIGGERED_BY)

    engine = create_engine(DB_URL)
    raw = extract(SOURCE_FILES)

    clean_customers, rej_customers = transform_customers(raw["customers"])
    clean_products, rej_products = transform_products(raw["products"])

    rejections = pd.concat([rej_customers, rej_products], ignore_index=True)

    try:
        run_pipeline(
            engine=engine,
            raw=raw,
            clean_customers=clean_customers,
            clean_products=clean_products,
            transform_sales=transform_sales,
            rejections=rejections,
            batch_date=BATCH_DATE,
            dq_thresholds=DQ_THRESHOLDS,
            triggered_by=TRIGGERED_BY,
            git_sha=GIT_SHA,
        )
    except Exception:
        log.error("[run] Pipeline failed - see etl_audit_log for details")
        sys.exit(1)

    log.info("[run] Pipeline finished successfully")


if __name__ == "__main__":
    main()

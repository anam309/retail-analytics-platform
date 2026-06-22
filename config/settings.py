"""
config/settings.py — Central configuration for the retail ETL pipeline.

Override any value with environment variables:
    DATABASE_URL=postgresql://...  python3 -m etl.run
    BATCH_DATE=2024-03-15          python3 -m etl.run
"""

import os
from datetime import date
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────

BASE_DIR     = Path(__file__).parent.parent
DATA_DIR     = BASE_DIR / "data"
RAW_DIR      = DATA_DIR / "raw"
REJECTED_DIR = DATA_DIR / "rejected"
LOG_DIR      = BASE_DIR / "logs"

for _d in (RAW_DIR, REJECTED_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ── Database ──────────────────────────────────────────────────────────────────

DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:password@localhost:5432/retail_analytics",
)

SCHEMA_STAGING   = "staging"
SCHEMA_WAREHOUSE = "warehouse"

# ── Pipeline runtime ──────────────────────────────────────────────────────────

# Set BATCH_DATE env var to reprocess a specific date (e.g. for reruns).
# Defaults to today.
_batch_env = os.getenv("BATCH_DATE")
BATCH_DATE: date = date.fromisoformat(_batch_env) if _batch_env else date.today()

TRIGGERED_BY = os.getenv("TRIGGERED_BY", "manual")   # 'airflow', 'dbt', 'manual'
GIT_SHA      = os.getenv("GIT_SHA")                   # set by CI/CD

# ── Data quality thresholds ───────────────────────────────────────────────────
# Breach any of these and the pipeline logs a warning (not a failure by default).

DQ_THRESHOLDS = {
    "max_unknown_customer_pct": 5.0,    # pct of fact rows with customer_sk = -1
    "max_unknown_product_pct":  5.0,    # pct of fact rows with product_sk  = -1
    "max_negative_margin_pct":  2.0,    # pct of fact rows with gross_profit < 0
    "min_volume_pct_of_prev":   50.0,   # total rows must be >= 50% of yesterday's load
}

# ── Source file names ─────────────────────────────────────────────────────────

SOURCE_FILES = {
    "customers": RAW_DIR / "customers.csv",
    "products":  RAW_DIR / "products.csv",
    "sales":     RAW_DIR / "sales.csv",
}

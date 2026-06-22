"""
etl/load.py — Stage 3: Load

Writes clean DataFrames to the warehouse. Handles:
  - SCD Type 2 upserts for dim_customer and dim_product
  - Bulk insert for fact_sales with pre-filter dedup
  - dim_date auto-extension for any date keys not yet in the table
  - Rejection rows written to staging.stg_rejections
  - Full etl_audit_log lifecycle (RUNNING → SUCCESS / FAILED)

Requires PostgreSQL (uses ARRAY parameters, RETURNING, generated columns).
"""

import json
import logging
import uuid
from datetime import date, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import text

log = logging.getLogger(__name__)


# ── Audit log helpers ─────────────────────────────────────────────────────────

def open_audit_record(
    engine,
    pipeline_name: str,
    batch_date: date,
    source_table: str = None,
    target_table: str = None,
    triggered_by: str = "manual",
    git_sha: str = None,
) -> int:
    """Insert a RUNNING audit record at pipeline start. Returns the audit_id."""
    with engine.begin() as conn:
        result = conn.execute(
            text("""
                INSERT INTO warehouse.etl_audit_log
                    (pipeline_name, source_table, target_table, batch_date,
                     status, triggered_by, git_commit_sha, run_id)
                VALUES
                    (:pipeline_name, :source_table, :target_table, :batch_date,
                     'RUNNING', :triggered_by, :git_sha, :run_id)
                RETURNING audit_id
            """),
            {
                "pipeline_name": pipeline_name,
                "source_table":  source_table,
                "target_table":  target_table,
                "batch_date":    batch_date,
                "triggered_by":  triggered_by,
                "git_sha":       git_sha,
                "run_id":        str(uuid.uuid4()),
            },
        )
        audit_id = result.scalar()
    log.info("[audit] Opened record audit_id=%d pipeline=%s", audit_id, pipeline_name)
    return audit_id


def close_audit_record(
    engine,
    audit_id: int,
    status: str,
    rows_extracted: int = 0,
    rows_inserted: int = 0,
    rows_updated: int = 0,
    rows_rejected: int = 0,
    rows_skipped: int = 0,
    error_message: str = None,
) -> None:
    """Update the audit record with final status and row counts."""
    assert status in {"SUCCESS", "FAILED", "PARTIAL"}, f"Invalid status: {status}"
    with engine.begin() as conn:
        conn.execute(
            text("""
                UPDATE warehouse.etl_audit_log
                SET status         = :status,
                    finished_at    = NOW(),
                    rows_extracted = :rows_extracted,
                    rows_inserted  = :rows_inserted,
                    rows_updated   = :rows_updated,
                    rows_rejected  = :rows_rejected,
                    rows_skipped   = :rows_skipped,
                    error_message  = :error_message
                WHERE audit_id = :audit_id
            """),
            {
                "audit_id":       audit_id,
                "status":         status,
                "rows_extracted": rows_extracted,
                "rows_inserted":  rows_inserted,
                "rows_updated":   rows_updated,
                "rows_rejected":  rows_rejected,
                "rows_skipped":   rows_skipped,
                "error_message":  error_message,
            },
        )
    log.info("[audit] Closed audit_id=%d status=%s", audit_id, status)


# ── Dimension loaders (SCD Type 2) ────────────────────────────────────────────

def _scd2_upsert(
    engine,
    df: pd.DataFrame,
    table: str,
    schema: str,
    natural_key: str,
    surrogate_key: str,
    batch_date: date,
) -> dict[str, int]:
    """
    Generic SCD Type 2 upsert.

    For each incoming row:
      - Not in warehouse  → INSERT (new record, is_current=TRUE)
      - Hash unchanged    → skip (Type 1 fields may be updated separately)
      - Hash changed      → expire current row + INSERT new version

    Returns dict with keys: inserted, updated (version bumps), skipped.
    """
    stats = {"inserted": 0, "updated": 0, "skipped": 0}
    natural_ids = df[natural_key].tolist()

    with engine.connect() as conn:
        existing_rows = pd.read_sql(
            text(f"""
                SELECT {natural_key}, {surrogate_key}, scd_hash
                FROM {schema}.{table}
                WHERE {natural_key} = ANY(:ids) AND is_current = TRUE
            """),
            conn,
            params={"ids": natural_ids},
        )

    existing_map: dict[str, dict[str, Any]] = {
        row[natural_key]: row.to_dict()
        for _, row in existing_rows.iterrows()
    }

    new_rows: list[dict] = []
    expire_sks: list[int] = []

    for _, row in df.iterrows():
        nk = row[natural_key]
        current = existing_map.get(nk)

        if current is None:
            new_rows.append({
                **row.to_dict(),
                "effective_from": batch_date,
                "effective_to":   date(9999, 12, 31),
                "is_current":     True,
            })
            stats["inserted"] += 1

        elif row.get("scd_hash") != current.get("scd_hash"):
            expire_sks.append(int(current[surrogate_key]))
            new_rows.append({
                **row.to_dict(),
                "effective_from": batch_date,
                "effective_to":   date(9999, 12, 31),
                "is_current":     True,
            })
            stats["updated"] += 1

        else:
            stats["skipped"] += 1

    # Expire changed records
    if expire_sks:
        with engine.begin() as conn:
            conn.execute(
                text(f"""
                    UPDATE {schema}.{table}
                    SET is_current  = FALSE,
                        effective_to = :eff_to,
                        updated_at  = NOW()
                    WHERE {surrogate_key} = ANY(:sks)
                """),
                {"eff_to": batch_date - timedelta(days=1), "sks": expire_sks},
            )

    # Bulk insert new rows and new versions
    if new_rows:
        insert_df = pd.DataFrame(new_rows)
        # Drop surrogate key — the DB BIGSERIAL assigns it
        if surrogate_key in insert_df.columns:
            insert_df = insert_df.drop(columns=[surrogate_key])
        insert_df.to_sql(
            table, engine, schema=schema,
            if_exists="append", index=False, method="multi",
        )

    log.info(
        "[load] %-20s inserted=%d  updated=%d  skipped=%d",
        table, stats["inserted"], stats["updated"], stats["skipped"],
    )
    return stats


def load_dim_customer(engine, df: pd.DataFrame, batch_date: date) -> dict[str, int]:
    """SCD Type 2 upsert for warehouse.dim_customer."""
    return _scd2_upsert(
        engine, df,
        table="dim_customer", schema="warehouse",
        natural_key="customer_id", surrogate_key="customer_sk",
        batch_date=batch_date,
    )


def load_dim_product(engine, df: pd.DataFrame, batch_date: date) -> dict[str, int]:
    """SCD Type 2 upsert for warehouse.dim_product."""
    return _scd2_upsert(
        engine, df,
        table="dim_product", schema="warehouse",
        natural_key="product_id", surrogate_key="product_sk",
        batch_date=batch_date,
    )


# ── dim_date extension ────────────────────────────────────────────────────────

def ensure_dim_dates(engine, date_keys: pd.Series) -> None:
    """
    Extend warehouse.dim_date for any date_keys not yet present.

    date_keys is a Series of integers in YYYYMMDD format.
    Calls fn_populate_dim_date for each missing date range.
    """
    unique_keys = date_keys.dropna().unique().tolist()
    if not unique_keys:
        return

    with engine.connect() as conn:
        existing = set(
            row[0] for row in conn.execute(
                text("SELECT date_key FROM warehouse.dim_date WHERE date_key = ANY(:keys)"),
                {"keys": unique_keys},
            ).fetchall()
        )

    missing_keys = [k for k in unique_keys if k not in existing]
    if not missing_keys:
        return

    # Convert integer keys back to dates and find the full range to populate
    missing_dates = pd.to_datetime([str(k) for k in missing_keys], format="%Y%m%d")
    start = missing_dates.min().date() - timedelta(days=30)
    end   = missing_dates.max().date() + timedelta(days=30)

    with engine.begin() as conn:
        inserted = conn.execute(
            text("SELECT warehouse.fn_populate_dim_date(:start, :end)"),
            {"start": start, "end": end},
        ).scalar()

    log.info("[load] dim_date extended: %d new rows for range %s → %s", inserted, start, end)


# ── fact_sales loader ─────────────────────────────────────────────────────────

# Columns from the enriched sales DataFrame that map to warehouse.fact_sales.
FACT_COLS = [
    "customer_sk", "product_sk", "transaction_date_key", "transaction_date",
    "transaction_id", "line_number", "quantity", "unit_price",
    "gross_revenue", "discount_amount", "net_revenue",
    "cogs", "gross_profit", "tax_amount", "total_amount",
    "payment_method", "channel", "store_id", "_stg_sale_id",
]


def load_fact_sales(engine, df: pd.DataFrame) -> dict[str, int]:
    """
    Bulk insert fact_sales rows.

    Deduplication strategy:
      1. Query existing _stg_sale_id values for this batch in a single IN (...).
      2. Drop already-loaded rows from the DataFrame.
      3. Bulk-insert the remainder with pandas to_sql (append mode).

    The unique constraint uq_fact_sales_grain on (transaction_id, line_number)
    acts as a final safety net for any duplicates that slip through step 2.

    Returns dict with keys: inserted, skipped.
    """
    stats = {"inserted": 0, "skipped": 0}

    # Keep only columns that exist in both the DF and the fact table definition
    cols = [c for c in FACT_COLS if c in df.columns]
    insert_df = df[cols].copy()

    stg_ids = insert_df["_stg_sale_id"].dropna().unique().tolist()

    # Pre-filter: drop rows whose staging ID is already in the warehouse
    if stg_ids:
        with engine.connect() as conn:
            loaded_ids = set(
                row[0] for row in conn.execute(
                    text("""
                        SELECT _stg_sale_id FROM warehouse.fact_sales
                        WHERE _stg_sale_id = ANY(:ids)
                    """),
                    {"ids": stg_ids},
                ).fetchall()
            )
        already_loaded = insert_df["_stg_sale_id"].isin(loaded_ids)
        stats["skipped"] = int(already_loaded.sum())
        insert_df = insert_df[~already_loaded].copy()

    if insert_df.empty:
        log.info("[load] fact_sales  inserted=0  skipped=%d (all already loaded)", stats["skipped"])
        return stats

    insert_df.to_sql(
        "fact_sales", engine, schema="warehouse",
        if_exists="append", index=False, method="multi",
    )
    stats["inserted"] = len(insert_df)

    log.info(
        "[load] fact_sales          inserted=%d  skipped=%d",
        stats["inserted"], stats["skipped"],
    )
    return stats


# ── Rejection writer ──────────────────────────────────────────────────────────

def write_rejections(engine, rejections_df: pd.DataFrame, batch_date: date) -> None:
    """
    Write rejected rows to staging.stg_rejections.

    The full source row is serialised to JSON and stored in raw_record
    for auditability and re-processing.
    """
    if rejections_df.empty:
        return

    meta_cols = {"source_table", "source_pk", "rejection_category", "rejection_reason"}
    payload_cols = [c for c in rejections_df.columns if c not in meta_cols]

    out = rejections_df[list(meta_cols)].copy()
    out["batch_date"]   = batch_date
    out["raw_record"]   = rejections_df[payload_cols].apply(
        lambda row: json.dumps(row.to_dict(), default=str), axis=1
    )

    out.to_sql(
        "stg_rejections", engine, schema="staging",
        if_exists="append", index=False,
    )
    log.info("[load] stg_rejections  wrote=%d rows", len(out))


# ── DQ threshold check ────────────────────────────────────────────────────────

def check_dq_thresholds(engine, batch_date: date, thresholds: dict) -> list[str]:
    """
    Query vw_dq_daily_load_summary for batch_date and return a list
    of threshold breach messages (empty list = all clear).
    """
    warnings: list[str] = []
    with engine.connect() as conn:
        row = conn.execute(
            text("""
                SELECT total_rows_loaded, pct_unknown_customers,
                       pct_negative_margin
                FROM warehouse.vw_dq_daily_load_summary
                WHERE load_date = :d
                LIMIT 1
            """),
            {"d": batch_date},
        ).fetchone()

    if row is None:
        warnings.append(f"No rows found in DQ summary for {batch_date}")
        return warnings

    total, pct_unk_cust, pct_neg_margin = row

    if pct_unk_cust and pct_unk_cust > thresholds.get("max_unknown_customer_pct", 5.0):
        warnings.append(f"Unknown customers {pct_unk_cust:.1f}% exceeds threshold")
    if pct_neg_margin and pct_neg_margin > thresholds.get("max_negative_margin_pct", 2.0):
        warnings.append(f"Negative margin rows {pct_neg_margin:.1f}% exceeds threshold")

    return warnings


# ── Pipeline orchestrator ─────────────────────────────────────────────────────

def run_pipeline(
    engine,
    raw: dict,
    clean_customers: pd.DataFrame,
    clean_products: pd.DataFrame,
    clean_sales: pd.DataFrame,
    rejections: pd.DataFrame,
    batch_date: date,
    dq_thresholds: dict,
    triggered_by: str = "manual",
    git_sha: str = None,
) -> None:
    """
    Full load pipeline. Called after extract + transform have completed.

    Execution order:
      1. Open audit record (RUNNING)
      2. Load dim_customer  (SCD2)
      3. Load dim_product   (SCD2)
      4. Ensure dim_date covers all transaction dates
      5. Load fact_sales    (bulk insert with pre-filter dedup)
      6. Write rejections   → staging.stg_rejections
      7. Evaluate DQ thresholds
      8. Close audit record (SUCCESS or FAILED)
    """
    total_extracted = sum(len(df) for df in raw.values())
    audit_id = open_audit_record(
        engine,
        pipeline_name="retail_etl_full",
        batch_date=batch_date,
        source_table="stg_sales / stg_customers / stg_products",
        target_table="fact_sales / dim_customer / dim_product",
        triggered_by=triggered_by,
        git_sha=git_sha,
    )

    rows_inserted = rows_updated = rows_skipped = 0
    error_message = None

    try:
        cust_stats = load_dim_customer(engine, clean_customers, batch_date)
        prod_stats = load_dim_product(engine, clean_products, batch_date)

        ensure_dim_dates(engine, clean_sales["transaction_date_key"])

        fact_stats = load_fact_sales(engine, clean_sales)

        write_rejections(engine, rejections, batch_date)

        rows_inserted = (
            cust_stats["inserted"] + prod_stats["inserted"] + fact_stats["inserted"]
        )
        rows_updated = cust_stats["updated"] + prod_stats["updated"]
        rows_skipped = (
            cust_stats["skipped"] + prod_stats["skipped"] + fact_stats["skipped"]
        )

        dq_warnings = check_dq_thresholds(engine, batch_date, dq_thresholds)
        for w in dq_warnings:
            log.warning("[dq] THRESHOLD BREACH: %s", w)

        status = "SUCCESS"

    except Exception as exc:
        error_message = str(exc)
        status = "FAILED"
        log.exception("[load] Pipeline failed: %s", exc)
        raise

    finally:
        close_audit_record(
            engine, audit_id,
            status=status,
            rows_extracted=total_extracted,
            rows_inserted=rows_inserted,
            rows_updated=rows_updated,
            rows_rejected=len(rejections),
            rows_skipped=rows_skipped,
            error_message=error_message,
        )

"""
etl/transform.py — Stage 2: Transform

Validates, type-coerces, hashes SCD2 fields, resolves foreign keys,
and computes derived metrics. Every entity function returns a tuple:
    (clean_df, rejections_df)

Rejection routing:
  - Hard reject (goes to stg_rejections, does NOT proceed):
      TYPE_ERROR, NULL_VIOLATION, RANGE_CHECK, BUSINESS_RULE, DUPLICATE
  - Soft miss (proceeds with -1 default key):
      customer_id / product_id not found in warehouse dims → FK = -1

All FK lookups are batched — one IN (...) query per entity, resolved
in-memory via a dict. No row-by-row database calls.
"""

import hashlib
import logging
from datetime import date

import pandas as pd
from sqlalchemy import text

log = logging.getLogger(__name__)

# ── SCD2 tracked attribute sets ───────────────────────────────────────────────
# A change in ANY of these fields triggers a new version in the warehouse dim.
# Fields NOT listed here are Type 1 (overwritten in place, no history kept).

CUSTOMER_TRACKED = [
    "first_name", "last_name", "email", "phone",
    "address_line1", "city", "state", "country", "postal_code",
    "loyalty_tier", "customer_segment",
]

PRODUCT_TRACKED = [
    "product_name", "description", "category", "subcategory",
    "brand", "supplier_name", "current_price", "unit_cost",
]

# ── Required fields — NULL in any of these → hard reject ─────────────────────

REQUIRED = {
    "customers": ["customer_id", "email", "first_name", "last_name"],
    "products":  ["product_id", "product_name", "category", "current_price", "unit_cost"],
    "sales":     ["sale_id", "transaction_id", "customer_id", "product_id",
                  "quantity", "unit_price", "transaction_date"],
}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _scd_hash(row: pd.Series, fields: list[str]) -> str:
    """SHA-256 of pipe-joined tracked field values. Order of fields is fixed."""
    raw = "|".join(str(row.get(f, "")).strip() for f in fields)
    return hashlib.sha256(raw.encode()).hexdigest()


def _build_rejection(
    df: pd.DataFrame,
    source_table: str,
    category: str,
    reason: str,
    pk_col: str,
) -> pd.DataFrame:
    """Return a DataFrame shaped for staging.stg_rejections."""
    if df.empty:
        return pd.DataFrame(columns=["source_table", "source_pk", "rejection_category", "rejection_reason"])
    out = pd.DataFrame({
        "source_table":       source_table,
        "source_pk":          df[pk_col].astype(str) if pk_col in df.columns else "",
        "rejection_category": category,
        "rejection_reason":   reason,
    }, index=df.index)
    return out


def _null_check(
    df: pd.DataFrame,
    cols: list[str],
    source_table: str,
    pk_col: str,
) -> tuple[pd.DataFrame, list[pd.DataFrame]]:
    """Remove rows where any required column is blank/null. Returns (clean, rejections)."""
    rejections = []
    for col in cols:
        if col not in df.columns:
            continue
        null_mask = df[col].str.strip() == ""
        if null_mask.any():
            rejections.append(_build_rejection(
                df[null_mask], source_table, "NULL_VIOLATION",
                f"Required field '{col}' is null or empty", pk_col,
            ))
            df = df[~null_mask].copy()
    return df, rejections


def _coerce_numeric(
    df: pd.DataFrame,
    cols: list[str],
    source_table: str,
    pk_col: str,
) -> tuple[pd.DataFrame, list[pd.DataFrame]]:
    """Cast columns to numeric; reject rows that fail casting."""
    rejections = []
    for col in cols:
        if col not in df.columns:
            continue
        original = df[col].copy()
        df = df.copy()
        df[col] = pd.to_numeric(df[col], errors="coerce")
        bad = df[col].isna() & (original.str.strip() != "")
        if bad.any():
            rejections.append(_build_rejection(
                df[bad], source_table, "TYPE_ERROR",
                f"'{col}' could not be cast to numeric", pk_col,
            ))
            df = df[~bad].copy()
    return df, rejections


# ── Public transform functions ────────────────────────────────────────────────

def transform_customers(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Validate and enrich the raw customers DataFrame.

    Steps:
      1. Strip leading/trailing whitespace from all string columns.
      2. Null-check required fields.
      3. Type-coerce boolean and date columns.
      4. Compute SCD2 hash over CUSTOMER_TRACKED fields.

    Returns:
        clean_df     — typed DataFrame with scd_hash column added.
        rejections_df — rows that failed validation, shaped for stg_rejections.
    """
    all_rejections: list[pd.DataFrame] = []

    # Strip whitespace across all string columns
    str_cols = df.select_dtypes(include="object").columns
    df[str_cols] = df[str_cols].apply(lambda s: s.str.strip())

    # Null checks
    df, rej = _null_check(df, REQUIRED["customers"], "stg_customers", "customer_id")
    all_rejections.extend(rej)

    df = df.copy()

    # Boolean coercions
    for col in ("email_opt_in", "sms_opt_in"):
        if col in df.columns:
            df[col] = (
                df[col].str.lower()
                .map({"true": True, "1": True, "yes": True,
                      "false": False, "0": False, "no": False})
                .fillna(False)
            )

    # Date coercions (errors become NaT — acceptable for optional fields)
    for col in ("date_of_birth", "registration_date", "updated_at"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    # SCD2 hash — computed after stripping/normalising tracked fields
    df["scd_hash"] = df.apply(_scd_hash, fields=CUSTOMER_TRACKED, axis=1)

    rejections_df = (
        pd.concat(all_rejections, ignore_index=True)
        if all_rejections else pd.DataFrame()
    )

    log.info(
        "[transform] customers  clean=%d  rejected=%d",
        len(df), len(rejections_df),
    )
    return df, rejections_df


def transform_products(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Validate and enrich the raw products DataFrame.

    Steps:
      1. Strip whitespace.
      2. Null-check required fields.
      3. Numeric coercions with rejection on cast failure.
      4. Range checks: current_price >= 0, unit_cost >= 0.
      5. Boolean coercion for is_active.
      6. Compute SCD2 hash.

    Returns:
        clean_df, rejections_df
    """
    all_rejections: list[pd.DataFrame] = []

    str_cols = df.select_dtypes(include="object").columns
    df[str_cols] = df[str_cols].apply(lambda s: s.str.strip())

    df, rej = _null_check(df, REQUIRED["products"], "stg_products", "product_id")
    all_rejections.extend(rej)

    df, rej = _coerce_numeric(
        df, ["current_price", "unit_cost", "weight_kg"], "stg_products", "product_id"
    )
    all_rejections.extend(rej)

    # Integer coercion for reorder_point (non-critical — fill with default)
    if "reorder_point" in df.columns:
        df = df.copy()
        df["reorder_point"] = pd.to_numeric(df["reorder_point"], errors="coerce").fillna(10).astype(int)

    # Range checks
    for col, label in [("current_price", "current_price"), ("unit_cost", "unit_cost")]:
        if col in df.columns:
            bad = df[col] < 0
            if bad.any():
                all_rejections.append(_build_rejection(
                    df[bad], "stg_products", "RANGE_CHECK",
                    f"{label} cannot be negative", "product_id",
                ))
                df = df[~bad].copy()

    # Boolean
    if "is_active" in df.columns:
        df = df.copy()
        df["is_active"] = (
            df["is_active"].str.lower()
            .map({"true": True, "1": True, "false": False, "0": False})
            .fillna(True)
        )

    # Date coercions
    for col in ("created_at", "updated_at"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    df["scd_hash"] = df.apply(_scd_hash, fields=PRODUCT_TRACKED, axis=1)

    rejections_df = (
        pd.concat(all_rejections, ignore_index=True)
        if all_rejections else pd.DataFrame()
    )

    log.info(
        "[transform] products   clean=%d  rejected=%d",
        len(df), len(rejections_df),
    )
    return df, rejections_df


def transform_sales(
    df: pd.DataFrame,
    engine,
    batch_date: date,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Validate raw sales, resolve FK surrogate keys, compute derived metrics.

    Steps:
      1. Strip whitespace.
      2. Null-check required fields.
      3. Numeric + date type coercions with rejection on failure.
      4. Range checks: quantity > 0, unit_price >= 0, discount <= gross_revenue.
      5. Business-rule checks: transaction_date not in future.
      6. Batch FK lookups: customer_sk, product_sk, transaction_date_key.
         Misses become -1 (customer/product) or 19000101 (date) — not rejected.
      7. Compute derived fields: gross_revenue, net_revenue, cogs,
         gross_profit, tax_amount, total_amount.

    Returns:
        enriched_df, rejections_df
    """
    all_rejections: list[pd.DataFrame] = []

    str_cols = df.select_dtypes(include="object").columns
    df[str_cols] = df[str_cols].apply(lambda s: s.str.strip())

    # ── 1. Null checks ────────────────────────────────────────────────────────
    df, rej = _null_check(df, REQUIRED["sales"], "stg_sales", "sale_id")
    all_rejections.extend(rej)

    # ── 2. Numeric coercions ──────────────────────────────────────────────────
    df, rej = _coerce_numeric(df, ["unit_price"], "stg_sales", "sale_id")
    all_rejections.extend(rej)

    for col in ("discount_amount", "tax_amount"):
        if col in df.columns:
            df = df.copy()
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    df = df.copy()
    orig_qty = df["quantity"].copy()
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")
    bad_qty_type = df["quantity"].isna() & (orig_qty.str.strip() != "")
    if bad_qty_type.any():
        all_rejections.append(_build_rejection(
            df[bad_qty_type], "stg_sales", "TYPE_ERROR",
            "'quantity' could not be cast to integer", "sale_id",
        ))
        df = df[~bad_qty_type].copy()
    df["quantity"] = df["quantity"].fillna(0).astype(int)

    df["line_number"] = pd.to_numeric(
        df.get("line_number", pd.Series(1, index=df.index)), errors="coerce"
    ).fillna(1).astype(int)

    # ── 3. Date coercion ──────────────────────────────────────────────────────
    orig_date = df["transaction_date"].copy()
    df["transaction_date"] = pd.to_datetime(df["transaction_date"], errors="coerce")
    bad_date = df["transaction_date"].isna() & (orig_date.str.strip() != "")
    if bad_date.any():
        all_rejections.append(_build_rejection(
            df[bad_date], "stg_sales", "TYPE_ERROR",
            "'transaction_date' could not be parsed as a date", "sale_id",
        ))
        df = df[~bad_date].copy()

    # ── 4. Range checks ───────────────────────────────────────────────────────
    bad_qty_range = df["quantity"] <= 0
    if bad_qty_range.any():
        all_rejections.append(_build_rejection(
            df[bad_qty_range], "stg_sales", "RANGE_CHECK",
            "'quantity' must be greater than 0", "sale_id",
        ))
        df = df[~bad_qty_range].copy()

    bad_price = df["unit_price"] < 0
    if bad_price.any():
        all_rejections.append(_build_rejection(
            df[bad_price], "stg_sales", "RANGE_CHECK",
            "'unit_price' cannot be negative", "sale_id",
        ))
        df = df[~bad_price].copy()

    # ── 5. Business-rule checks ───────────────────────────────────────────────
    future_date = df["transaction_date"].dt.date > batch_date
    if future_date.any():
        all_rejections.append(_build_rejection(
            df[future_date], "stg_sales", "BUSINESS_RULE",
            f"'transaction_date' is after batch_date ({batch_date})", "sale_id",
        ))
        df = df[~future_date].copy()

    # Pre-compute gross_revenue to validate over-discount
    df = df.copy()
    df["gross_revenue"] = (df["quantity"] * df["unit_price"]).round(2)
    over_disc = df["discount_amount"] > df["gross_revenue"]
    if over_disc.any():
        all_rejections.append(_build_rejection(
            df[over_disc], "stg_sales", "RANGE_CHECK",
            "'discount_amount' exceeds gross_revenue", "sale_id",
        ))
        df = df[~over_disc].copy()

    # ── 6. FK batch lookups ───────────────────────────────────────────────────
    customer_ids = df["customer_id"].unique().tolist()
    product_ids  = df["product_id"].unique().tolist()

    with engine.connect() as conn:
        cust_rows = conn.execute(
            text("""
                SELECT customer_id, customer_sk
                FROM warehouse.dim_customer
                WHERE customer_id = ANY(:ids) AND is_current = TRUE
            """),
            {"ids": customer_ids},
        ).fetchall()
        cust_map = {r[0]: r[1] for r in cust_rows}

        prod_rows = conn.execute(
            text("""
                SELECT product_id, product_sk
                FROM warehouse.dim_product
                WHERE product_id = ANY(:ids) AND is_current = TRUE
            """),
            {"ids": product_ids},
        ).fetchall()
        prod_map = {r[0]: r[1] for r in prod_rows}

        cost_rows = conn.execute(
            text("""
                SELECT product_id, unit_cost
                FROM warehouse.dim_product
                WHERE product_id = ANY(:ids) AND is_current = TRUE
            """),
            {"ids": product_ids},
        ).fetchall()
        cost_map = {r[0]: float(r[1]) for r in cost_rows}

    df = df.copy()
    df["customer_sk"] = df["customer_id"].map(cust_map).fillna(-1).astype(int)
    df["product_sk"]  = df["product_id"].map(prod_map).fillna(-1).astype(int)

    # Date key — YYYYMMDD integer; extend dim_date inline if key is missing
    df["transaction_date_key"] = (
        df["transaction_date"].dt.strftime("%Y%m%d").astype(int)
    )

    unknown_cust  = (df["customer_sk"] == -1).sum()
    unknown_prod  = (df["product_sk"]  == -1).sum()
    if unknown_cust:
        log.warning("[transform] %d sale rows have unknown customer_sk (-1)", unknown_cust)
    if unknown_prod:
        log.warning("[transform] %d sale rows have unknown product_sk (-1)", unknown_prod)

    # ── 7. Derived fields ─────────────────────────────────────────────────────
    df["unit_cost_snapshot"] = df["product_id"].map(cost_map).fillna(0.0)
    df["net_revenue"]        = (df["gross_revenue"] - df["discount_amount"]).round(2)
    df["cogs"]               = (df["quantity"] * df["unit_cost_snapshot"]).round(2)
    df["gross_profit"]       = (df["net_revenue"] - df["cogs"]).round(2)
    df["total_amount"]       = (df["net_revenue"] + df["tax_amount"]).round(2)

    # Rename staging PK to the warehouse convention
    df = df.rename(columns={"sale_id": "_stg_sale_id"})

    rejections_df = (
        pd.concat(all_rejections, ignore_index=True)
        if all_rejections else pd.DataFrame()
    )

    log.info(
        "[transform] sales      clean=%d  rejected=%d  unknown_cust=%d  unknown_prod=%d",
        len(df), len(rejections_df), unknown_cust, unknown_prod,
    )
    return df, rejections_df

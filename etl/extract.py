"""
etl/extract.py — Stage 1: Extract

Reads raw CSV files into DataFrames with all columns as str dtype.
No type casting, no business logic — that is transform's job.

Contract:
  - Raises FileNotFoundError if a source file is missing.
  - Raises ValueError if a file is empty or has missing required columns.
  - Returns a dict keyed by entity name ('customers', 'products', 'sales').
  - Every returned DataFrame has a _source_file metadata column appended.
"""

import logging
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

# Minimum columns expected from each source file.
# Any extra columns in the CSV are kept; only these are enforced.
EXPECTED_COLUMNS: dict[str, set[str]] = {
    "customers": {
        "customer_id", "first_name", "last_name", "email", "phone",
        "date_of_birth", "address_line1", "city", "state", "country",
        "postal_code", "loyalty_tier", "customer_segment",
        "email_opt_in", "sms_opt_in", "registration_date", "updated_at",
    },
    "products": {
        "product_id", "product_name", "description", "category", "subcategory",
        "brand", "supplier_name", "current_price", "unit_cost", "weight_kg",
        "is_active", "reorder_point", "created_at", "updated_at",
    },
    "sales": {
        "sale_id", "transaction_id", "line_number", "customer_id", "product_id",
        "transaction_date", "quantity", "unit_price", "discount_amount",
        "tax_amount", "payment_method", "channel", "store_id",
    },
}


def extract_file(path: Path, entity: str) -> pd.DataFrame:
    """
    Read one CSV source file.

    All columns are loaded as str (dtype=str, keep_default_na=False) so that
    downstream code distinguishes an empty string from a true NULL and no
    numeric conversion silently produces NaN before the validate stage runs.
    """
    if not path.exists():
        raise FileNotFoundError(f"Source file not found: {path}")

    df = pd.read_csv(path, dtype=str, keep_default_na=False)

    if df.empty:
        raise ValueError(f"Source file is empty: {path}")

    missing_cols = EXPECTED_COLUMNS[entity] - set(df.columns)
    if missing_cols:
        raise ValueError(
            f"[{entity}] Missing required columns: {sorted(missing_cols)}"
        )

    # Attach lightweight provenance metadata
    df["_source_file"] = path.name

    log.info(
        "[extract] %-10s  %6d rows  %2d columns  file=%s",
        entity, len(df), df.shape[1], path.name,
    )
    return df


def extract(source_files: dict[str, Path]) -> dict[str, pd.DataFrame]:
    """
    Extract all source files defined in source_files.

    Args:
        source_files: mapping of entity name → Path, e.g.
                      {'customers': Path('data/raw/customers.csv'), ...}

    Returns:
        Dict of raw DataFrames keyed by entity name.

    Raises:
        FileNotFoundError / ValueError on the first file that fails validation.
        A failed extract aborts the pipeline before any transforms run.
    """
    log.info("[extract] Starting extraction for %d entities", len(source_files))

    raw: dict[str, pd.DataFrame] = {}
    for entity, path in source_files.items():
        raw[entity] = extract_file(path, entity)

    total_rows = sum(len(df) for df in raw.values())
    log.info("[extract] Complete — %d total rows across %d files", total_rows, len(raw))
    return raw

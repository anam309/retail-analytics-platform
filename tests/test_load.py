from datetime import date

import pandas as pd
from sqlalchemy import text

from etl.load import load_dim_customer, load_fact_sales, load_staging


def test_load_dim_customer_ignores_extract_only_columns(db):
    """Regression test: extract.py appends `_source_file` to every raw
    DataFrame, but warehouse.dim_customer has no such column. _scd2_upsert
    must filter it out instead of trying to insert it (this used to crash
    every single load — see git history)."""
    df = pd.DataFrame([{
        "customer_id": "CUST-X", "first_name": "Ada", "last_name": "Lovelace",
        "email": "a@b.com", "_source_file": "customers.csv", "scd_hash": "h1",
    }])

    stats = load_dim_customer(db, df, date(2024, 1, 1))

    assert stats["inserted"] == 1


def test_fact_sales_unknown_fk_sentinel_row_exists(db):
    """Regression test: fact_sales.customer_sk/product_sk default to -1 for
    unresolved FKs, and the FK constraints require -1 to exist as a real row
    in dim_customer/dim_product — otherwise every fact insert with an
    unmatched customer/product throws ForeignKeyViolation."""
    with db.connect() as conn:
        cust = conn.execute(text(
            "SELECT 1 FROM warehouse.dim_customer WHERE customer_sk = -1"
        )).fetchone()
        prod = conn.execute(text(
            "SELECT 1 FROM warehouse.dim_product WHERE product_sk = -1"
        )).fetchone()

    assert cust is not None
    assert prod is not None


def test_load_fact_sales_dedup_skips_already_loaded_rows(db):
    row = {
        "customer_sk": -1, "product_sk": -1, "transaction_date_key": 20240101,
        "transaction_date": date(2024, 1, 1), "transaction_id": "TXN-DEDUP", "line_number": 1,
        "quantity": 1, "unit_price": 10.0, "gross_revenue": 10.0, "discount_amount": 0.0,
        "net_revenue": 10.0, "cogs": 0.0, "gross_profit": 10.0, "tax_amount": 0.0,
        "total_amount": 10.0, "payment_method": "Cash", "channel": "In-Store",
        "store_id": "STORE-001", "_stg_sale_id": "SALE-DEDUP",
    }
    df = pd.DataFrame([row])

    first = load_fact_sales(db, df)
    second = load_fact_sales(db, df)

    assert first == {"inserted": 1, "skipped": 0}
    assert second == {"inserted": 0, "skipped": 1}


def test_load_staging_lands_raw_rows_only_with_matching_columns(db):
    raw = {"customers": pd.DataFrame([{
        "customer_id": "CUST-Y", "first_name": "Ada", "_source_file": "customers.csv",
    }])}

    load_staging(db, raw)

    with db.connect() as conn:
        n = conn.execute(text(
            "SELECT COUNT(*) FROM staging.stg_customers WHERE customer_id = 'CUST-Y'"
        )).scalar()

    assert n == 1

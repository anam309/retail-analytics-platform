from datetime import date

import pandas as pd
from sqlalchemy import text

from etl.transform import transform_sales


def _seed_customer(db, customer_id="CUST-1"):
    with db.begin() as conn:
        conn.execute(text("""
            INSERT INTO warehouse.dim_customer
                (customer_id, first_name, last_name, effective_from, is_current, scd_hash)
            VALUES (:cid, 'Ada', 'Lovelace', '2020-01-01', TRUE, 'h')
        """), {"cid": customer_id})


def _seed_product(db, product_id="PROD-1"):
    with db.begin() as conn:
        conn.execute(text("""
            INSERT INTO warehouse.dim_product
                (product_id, product_name, category, current_price, unit_cost,
                 effective_from, is_current, scd_hash)
            VALUES (:pid, 'Widget', 'Tools', 10.00, 4.00, '2020-01-01', TRUE, 'h')
        """), {"pid": product_id})


def _sales_df(rows):
    return pd.DataFrame(rows, dtype=str).fillna("")


def _row(**overrides):
    row = {
        "sale_id": "SALE-1", "transaction_id": "TXN-1", "line_number": "1",
        "customer_id": "CUST-1", "product_id": "PROD-1",
        "transaction_date": "2024-01-01", "quantity": "2", "unit_price": "10.00",
        "discount_amount": "0", "tax_amount": "1.00", "payment_method": "Cash",
        "channel": "In-Store", "store_id": "STORE-001",
    }
    row.update(overrides)
    return row


def test_known_customer_and_product_resolve_fk(db):
    _seed_customer(db)
    _seed_product(db)

    clean, rejected = transform_sales(_sales_df([_row()]), db, date(2024, 6, 1))

    assert rejected.empty
    assert clean.iloc[0]["customer_sk"] != -1
    assert clean.iloc[0]["product_sk"] != -1


def test_unknown_customer_defaults_to_negative_one(db):
    _seed_product(db)

    clean, rejected = transform_sales(
        _sales_df([_row(sale_id="SALE-2", customer_id="NOBODY")]), db, date(2024, 6, 1),
    )

    assert rejected.empty
    assert clean.iloc[0]["customer_sk"] == -1


def test_future_transaction_date_is_rejected(db):
    clean, rejected = transform_sales(
        _sales_df([_row(sale_id="SALE-3", transaction_date="2099-01-01")]), db, date(2024, 6, 1),
    )

    assert clean.empty
    assert rejected.iloc[0]["rejection_category"] == "BUSINESS_RULE"


def test_zero_quantity_is_rejected(db):
    clean, rejected = transform_sales(
        _sales_df([_row(sale_id="SALE-4", quantity="0")]), db, date(2024, 6, 1),
    )

    assert clean.empty
    assert rejected.iloc[0]["rejection_category"] == "RANGE_CHECK"

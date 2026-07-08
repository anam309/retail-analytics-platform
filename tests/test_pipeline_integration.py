"""
End-to-end regression test: extract → transform → load against a real,
freshly-built schema. This is the test that would have caught both bugs
fixed in this project's early history (the `_source_file` column leak in
_scd2_upsert, and the missing -1 sentinel rows in dim_customer/dim_product)
before they ever reached a real run.
"""

from datetime import date

import pandas as pd
from sqlalchemy import text

from etl.load import run_pipeline
from etl.transform import transform_customers, transform_products, transform_sales

DQ_THRESHOLDS = {
    "max_unknown_customer_pct": 100.0,
    "max_unknown_product_pct": 100.0,
    "max_negative_margin_pct": 100.0,
    "min_volume_pct_of_prev": 0.0,
}


def _raw_customers():
    return pd.DataFrame([{
        "customer_id": "CUST-100", "first_name": "Ada", "last_name": "Lovelace",
        "email": "ada@example.com", "phone": "", "date_of_birth": "", "address_line1": "",
        "city": "", "state": "", "country": "", "postal_code": "", "loyalty_tier": "Gold",
        "customer_segment": "Regular", "email_opt_in": "true", "sms_opt_in": "false",
        "registration_date": "2020-01-01", "updated_at": "2020-01-01",
        "_source_file": "customers.csv",
    }])


def _raw_products():
    return pd.DataFrame([{
        "product_id": "PROD-100", "product_name": "Widget", "description": "", "category": "Tools",
        "subcategory": "", "brand": "", "supplier_name": "", "current_price": "19.99",
        "unit_cost": "8.00", "weight_kg": "0.5", "is_active": "true", "reorder_point": "10",
        "created_at": "2020-01-01", "updated_at": "2020-01-01", "_source_file": "products.csv",
    }])


def _raw_sales():
    return pd.DataFrame([{
        "sale_id": "SALE-100", "transaction_id": "TXN-100", "line_number": "1",
        "customer_id": "CUST-100", "product_id": "PROD-100", "transaction_date": "2024-01-01",
        "quantity": "2", "unit_price": "19.99", "discount_amount": "0", "tax_amount": "2.00",
        "payment_method": "Cash", "channel": "In-Store", "store_id": "STORE-001",
        "_source_file": "sales.csv",
    }])


def test_full_pipeline_loads_data_end_to_end(db):
    batch_date = date.today()
    raw = {"customers": _raw_customers(), "products": _raw_products(), "sales": _raw_sales()}

    clean_c, rej_c = transform_customers(raw["customers"])
    clean_p, rej_p = transform_products(raw["products"])
    rejections = pd.concat([rej_c, rej_p], ignore_index=True)

    run_pipeline(
        db, raw, clean_c, clean_p, transform_sales, rejections,
        batch_date, DQ_THRESHOLDS, triggered_by="pytest",
    )

    with db.connect() as conn:
        assert conn.execute(text(
            "SELECT COUNT(*) FROM staging.stg_customers WHERE customer_id = 'CUST-100'"
        )).scalar() == 1
        assert conn.execute(text(
            "SELECT COUNT(*) FROM warehouse.dim_customer WHERE customer_id = 'CUST-100'"
        )).scalar() == 1
        assert conn.execute(text(
            "SELECT COUNT(*) FROM warehouse.dim_product WHERE product_id = 'PROD-100'"
        )).scalar() == 1
        assert conn.execute(text(
            "SELECT COUNT(*) FROM warehouse.fact_sales WHERE _stg_sale_id = 'SALE-100'"
        )).scalar() == 1

        status = conn.execute(text(
            "SELECT status FROM warehouse.etl_audit_log ORDER BY audit_id DESC LIMIT 1"
        )).scalar()
        assert status == "SUCCESS"


def test_pipeline_is_idempotent_on_rerun(db):
    """Rerunning the same batch must not duplicate fact rows or dim versions."""
    batch_date = date.today()
    raw = {"customers": _raw_customers(), "products": _raw_products(), "sales": _raw_sales()}

    for _ in range(2):
        clean_c, rej_c = transform_customers(raw["customers"])
        clean_p, rej_p = transform_products(raw["products"])
        rejections = pd.concat([rej_c, rej_p], ignore_index=True)
        run_pipeline(
            db, raw, clean_c, clean_p, transform_sales, rejections,
            batch_date, DQ_THRESHOLDS, triggered_by="pytest",
        )

    with db.connect() as conn:
        assert conn.execute(text(
            "SELECT COUNT(*) FROM warehouse.fact_sales WHERE _stg_sale_id = 'SALE-100'"
        )).scalar() == 1
        assert conn.execute(text(
            "SELECT COUNT(*) FROM warehouse.dim_customer WHERE customer_id = 'CUST-100'"
        )).scalar() == 1


def test_same_batch_customer_and_product_resolve_fk_not_sentinel(db):
    """Regression test: a customer/product appearing for the first time in
    the same batch as their first sale must resolve to a real surrogate key,
    not fall back to -1. This requires dims to load before sales are
    FK-resolved — see run_pipeline's docstring for the execution order."""
    batch_date = date.today()
    raw = {"customers": _raw_customers(), "products": _raw_products(), "sales": _raw_sales()}

    clean_c, rej_c = transform_customers(raw["customers"])
    clean_p, rej_p = transform_products(raw["products"])
    rejections = pd.concat([rej_c, rej_p], ignore_index=True)

    run_pipeline(
        db, raw, clean_c, clean_p, transform_sales, rejections,
        batch_date, DQ_THRESHOLDS, triggered_by="pytest",
    )

    with db.connect() as conn:
        customer_sk, product_sk = conn.execute(text(
            "SELECT customer_sk, product_sk FROM warehouse.fact_sales WHERE _stg_sale_id = 'SALE-100'"
        )).fetchone()

    assert customer_sk != -1
    assert product_sk != -1

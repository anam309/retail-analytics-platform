from sqlalchemy import text

from etl.load import refresh_reporting_views
from reports.queries import (
    channel_payment_performance,
    data_quality_summary,
    monthly_revenue_trend,
    top_customers_by_ltv,
    top_products_by_revenue,
)


def _seed_one_sale(db):
    with db.begin() as conn:
        conn.execute(text("""
            INSERT INTO warehouse.dim_customer
                (customer_id, first_name, last_name, loyalty_tier, customer_segment,
                 registration_date, effective_from, is_current, scd_hash)
            VALUES ('CUST-R1', 'Rae', 'Report', 'Gold', 'Regular',
                    '2023-01-01', '2023-01-01', TRUE, 'h')
        """))
        conn.execute(text("""
            INSERT INTO warehouse.dim_product
                (product_id, product_name, category, current_price, unit_cost,
                 effective_from, is_current, scd_hash)
            VALUES ('PROD-R1', 'Reporting Widget', 'Tools', 50.00, 20.00,
                    '2023-01-01', TRUE, 'h')
        """))
        cust_sk = conn.execute(text(
            "SELECT customer_sk FROM warehouse.dim_customer WHERE customer_id = 'CUST-R1'"
        )).scalar()
        prod_sk = conn.execute(text(
            "SELECT product_sk FROM warehouse.dim_product WHERE product_id = 'PROD-R1'"
        )).scalar()
        conn.execute(text("""
            INSERT INTO warehouse.fact_sales
                (customer_sk, product_sk, transaction_date_key, transaction_date,
                 transaction_id, line_number, quantity, unit_price, gross_revenue,
                 discount_amount, net_revenue, unit_cost_snapshot, cogs, gross_profit,
                 tax_amount, total_amount, payment_method, channel, store_id, _stg_sale_id)
            VALUES
                (:cust_sk, :prod_sk, 20240115, '2024-01-15', 'TXN-R1', 1, 2, 50.00, 100.00,
                 0.00, 100.00, 20.00, 40.00, 60.00, 5.00, 105.00, 'Credit Card', 'Online',
                 '', 'SALE-R1')
        """), {"cust_sk": cust_sk, "prod_sk": prod_sk})


def test_refresh_reporting_views_succeeds(db):
    """Regression test: mv_channel_payment_analysis used to have no unique
    index, so REFRESH MATERIALIZED VIEW CONCURRENTLY failed for the whole
    procedure every time it was called."""
    refresh_reporting_views(db)


def test_business_reports_reflect_seeded_data(db):
    _seed_one_sale(db)
    refresh_reporting_views(db)

    products = top_products_by_revenue(db)
    assert (products["product_id"] == "PROD-R1").any()

    customers = top_customers_by_ltv(db)
    assert (customers["customer_id"] == "CUST-R1").any()

    channels = channel_payment_performance(db)
    assert (channels["channel"] == "Online").any()

    trend = monthly_revenue_trend(db)
    assert not trend.empty
    assert trend["revenue"].sum() >= 100.00

    dq = data_quality_summary(db)
    assert list(dq.columns) == [
        "load_date", "total_rows_loaded", "pct_unknown_customers",
        "pct_unknown_products", "pct_negative_margin", "total_revenue",
    ]

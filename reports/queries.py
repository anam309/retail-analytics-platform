"""
reports/queries.py — Business report queries against the warehouse.

Each function takes a SQLAlchemy engine and returns a pandas DataFrame. All
queries read from warehouse views and materialized views — see
retail_analytics_schema.sql and retail_analytics_schema_v2_improvements.sql
for their definitions. Nothing here writes to the database except via the
existing warehouse.sp_refresh_materialized_views() procedure (called from
etl.load.refresh_reporting_views).

These are the same tables/views a BI tool (Power BI, Looker) would point at
directly; this module exists for a lightweight standalone report when no BI
tool is wired up yet.
"""

import pandas as pd
from sqlalchemy import text


def monthly_revenue_trend(engine) -> pd.DataFrame:
    """Revenue, cost, and margin by month, across all channels."""
    query = text("""
        SELECT
            DATE_TRUNC('month', transaction_date)::DATE AS month,
            COUNT(DISTINCT transaction_id) AS orders,
            SUM(net_revenue) AS revenue,
            SUM(cogs) AS cogs,
            SUM(gross_profit) AS profit,
            ROUND(100.0 * SUM(gross_profit) / NULLIF(SUM(net_revenue), 0), 2) AS margin_pct
        FROM warehouse.fact_sales
        GROUP BY DATE_TRUNC('month', transaction_date)
        ORDER BY month
    """)
    return pd.read_sql(query, engine)


def top_products_by_revenue(engine, limit: int = 10) -> pd.DataFrame:
    """Top N products by total net revenue, from mv_product_performance."""
    query = text("""
        SELECT product_id, product_name, category, brand,
               total_quantity_sold, total_revenue, total_profit, profit_margin_pct
        FROM warehouse.mv_product_performance
        ORDER BY total_revenue DESC NULLS LAST
        LIMIT :limit
    """)
    return pd.read_sql(query, engine, params={"limit": limit})


def top_customers_by_ltv(engine, limit: int = 10) -> pd.DataFrame:
    """Top N customers by lifetime value, from mv_customer_ltv."""
    query = text("""
        SELECT customer_id, first_name, last_name, loyalty_tier, customer_segment,
               total_orders, total_spent, avg_order_value, years_as_customer
        FROM warehouse.mv_customer_ltv
        ORDER BY total_spent DESC NULLS LAST
        LIMIT :limit
    """)
    return pd.read_sql(query, engine, params={"limit": limit})


def channel_payment_performance(engine) -> pd.DataFrame:
    """Revenue and margin by channel and payment method, from mv_channel_payment_analysis."""
    query = text("""
        SELECT channel, payment_method,
               SUM(transaction_count) AS transaction_count,
               SUM(total_revenue) AS total_revenue,
               SUM(total_profit) AS total_profit,
               ROUND(100.0 * SUM(total_profit) / NULLIF(SUM(total_revenue), 0), 2) AS margin_pct
        FROM warehouse.mv_channel_payment_analysis
        GROUP BY channel, payment_method
        ORDER BY total_revenue DESC NULLS LAST
    """)
    return pd.read_sql(query, engine)


def data_quality_summary(engine, limit: int = 30) -> pd.DataFrame:
    """Daily load volume and data-quality signal, from vw_dq_daily_load_summary."""
    query = text("""
        SELECT load_date, total_rows_loaded, pct_unknown_customers,
               pct_unknown_products, pct_negative_margin, total_revenue
        FROM warehouse.vw_dq_daily_load_summary
        ORDER BY load_date DESC
        LIMIT :limit
    """)
    return pd.read_sql(query, engine, params={"limit": limit})

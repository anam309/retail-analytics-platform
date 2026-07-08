-- ============================================================================
-- Retail Analytics Data Warehouse — Schema Improvements (Phase 2)
-- ============================================================================
-- This script adds enhancements to the base schema:
--   - Additional performance indexes
--   - Materialized views for common analytics queries
--   - Advanced DQ monitoring
--   - Stored procedures for common operations
--
-- Prerequisites:
--   - retail_analytics_schema.sql must be run first
--   - All schemas and base tables must exist
--
-- ============================================================================

-- ────────────────────────────────────────────────────────────────────────────
-- ADDITIONAL INDEXES for common query patterns
-- ────────────────────────────────────────────────────────────────────────────

-- Composite index for revenue analysis by channel and date
CREATE INDEX IF NOT EXISTS idx_fact_sales_channel_date
    ON warehouse.fact_sales(channel, transaction_date DESC);

-- Index for payment method analysis
CREATE INDEX IF NOT EXISTS idx_fact_sales_payment_method
    ON warehouse.fact_sales(payment_method, net_revenue DESC);

-- Index for store performance analysis
CREATE INDEX IF NOT EXISTS idx_fact_sales_store_date
    ON warehouse.fact_sales(store_id, transaction_date DESC)
    WHERE store_id IS NOT NULL AND store_id != '';

-- Index for product category drill-down (via dim_product)
CREATE INDEX IF NOT EXISTS idx_dim_product_category
    ON warehouse.dim_product(category, is_current);

-- Index for customer loyalty/segment analysis
CREATE INDEX IF NOT EXISTS idx_dim_customer_loyalty
    ON warehouse.dim_customer(loyalty_tier, customer_segment, is_current);

-- ────────────────────────────────────────────────────────────────────────────
-- MATERIALIZED VIEW: Product Performance Summary
-- ────────────────────────────────────────────────────────────────────────────

CREATE MATERIALIZED VIEW IF NOT EXISTS warehouse.mv_product_performance AS
SELECT
    p.product_sk,
    p.product_id,
    p.product_name,
    p.category,
    p.brand,
    COUNT(DISTINCT fs.sale_sk) AS sale_count,
    SUM(fs.quantity) AS total_quantity_sold,
    SUM(fs.net_revenue) AS total_revenue,
    SUM(fs.cogs) AS total_cogs,
    SUM(fs.gross_profit) AS total_profit,
    ROUND(
        100.0 * SUM(fs.gross_profit) / NULLIF(SUM(fs.net_revenue), 0),
        2
    ) AS profit_margin_pct,
    AVG(fs.unit_price) AS avg_unit_price,
    MAX(fs.transaction_date) AS last_sale_date,
    COUNT(DISTINCT fs.transaction_date) AS days_with_sales
FROM warehouse.dim_product p
LEFT JOIN warehouse.fact_sales fs ON p.product_sk = fs.product_sk
WHERE p.is_current = TRUE
GROUP BY p.product_sk, p.product_id, p.product_name, p.category, p.brand;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_product_performance_sk
    ON warehouse.mv_product_performance(product_sk);

-- ────────────────────────────────────────────────────────────────────────────
-- MATERIALIZED VIEW: Customer Lifetime Value (CLV)
-- ────────────────────────────────────────────────────────────────────────────

CREATE MATERIALIZED VIEW IF NOT EXISTS warehouse.mv_customer_ltv AS
SELECT
    c.customer_sk,
    c.customer_id,
    c.first_name,
    c.last_name,
    c.loyalty_tier,
    c.customer_segment,
    c.registration_date,
    COUNT(DISTINCT fs.sale_sk) AS total_orders,
    COUNT(DISTINCT fs.transaction_date) AS order_dates,
    SUM(fs.net_revenue) AS total_spent,
    SUM(fs.gross_profit) AS total_profit,
    ROUND(AVG(fs.net_revenue), 2) AS avg_order_value,
    MAX(fs.transaction_date) AS last_purchase_date,
    ROUND(
        (MAX(fs.transaction_date) - c.registration_date) / 365.0,
        2
    ) AS years_as_customer
FROM warehouse.dim_customer c
LEFT JOIN warehouse.fact_sales fs ON c.customer_sk = fs.customer_sk
WHERE c.is_current = TRUE
GROUP BY c.customer_sk, c.customer_id, c.first_name, c.last_name,
         c.loyalty_tier, c.customer_segment, c.registration_date;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_customer_ltv_sk
    ON warehouse.mv_customer_ltv(customer_sk);

-- ────────────────────────────────────────────────────────────────────────────
-- MATERIALIZED VIEW: Channel & Payment Method Analysis
-- ────────────────────────────────────────────────────────────────────────────

CREATE MATERIALIZED VIEW IF NOT EXISTS warehouse.mv_channel_payment_analysis AS
SELECT
    fs.channel,
    fs.payment_method,
    DATE_TRUNC('month', fs.transaction_date)::DATE AS month,
    COUNT(DISTINCT fs.sale_sk) AS transaction_count,
    COUNT(DISTINCT fs.transaction_id) AS unique_orders,
    SUM(fs.quantity) AS total_quantity,
    SUM(fs.net_revenue) AS total_revenue,
    SUM(fs.cogs) AS total_cogs,
    SUM(fs.gross_profit) AS total_profit,
    ROUND(AVG(fs.net_revenue), 2) AS avg_transaction_value,
    ROUND(100.0 * SUM(fs.gross_profit) / NULLIF(SUM(fs.net_revenue), 0), 2) AS margin_pct
FROM warehouse.fact_sales fs
GROUP BY fs.channel, fs.payment_method, DATE_TRUNC('month', fs.transaction_date);

CREATE INDEX IF NOT EXISTS idx_mv_channel_payment_month
    ON warehouse.mv_channel_payment_analysis(month DESC);

-- REFRESH MATERIALIZED VIEW CONCURRENTLY requires a unique index; without one,
-- sp_refresh_materialized_views() fails on this view with
-- "cannot refresh materialized view concurrently".
CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_channel_payment_grain
    ON warehouse.mv_channel_payment_analysis(channel, payment_method, month);

-- ────────────────────────────────────────────────────────────────────────────
-- ENHANCED DATA QUALITY VIEW: Unknown Keys Detailed Report
-- ────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE VIEW warehouse.vw_data_quality_detailed AS
SELECT
    DATE(fs.created_at) AS load_date,
    'Unknown Customer' AS issue_type,
    COUNT(*) AS row_count,
    SUM(fs.net_revenue) AS revenue_impact,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY DATE(fs.created_at)), 2) AS pct_of_load
FROM warehouse.fact_sales fs
WHERE fs.customer_sk = -1
GROUP BY DATE(fs.created_at)

UNION ALL

SELECT
    DATE(fs.created_at),
    'Unknown Product',
    COUNT(*),
    SUM(fs.net_revenue),
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY DATE(fs.created_at)), 2)
FROM warehouse.fact_sales fs
WHERE fs.product_sk = -1
GROUP BY DATE(fs.created_at)

UNION ALL

SELECT
    DATE(fs.created_at),
    'Negative Margin',
    COUNT(*),
    SUM(fs.gross_profit),
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY DATE(fs.created_at)), 2)
FROM warehouse.fact_sales fs
WHERE fs.gross_profit < 0
GROUP BY DATE(fs.created_at)

ORDER BY load_date DESC, issue_type;

-- ────────────────────────────────────────────────────────────────────────────
-- ENHANCED AUDIT VIEW: Pipeline Performance Metrics
-- ────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE VIEW warehouse.vw_pipeline_performance AS
SELECT
    audit_id,
    pipeline_name,
    batch_date,
    status,
    rows_extracted,
    rows_inserted,
    rows_updated,
    rows_rejected,
    rows_skipped,
    (rows_inserted + rows_updated + rows_skipped) AS total_processed,
    ROUND(100.0 * rows_rejected / NULLIF(rows_extracted, 0), 2) AS rejection_rate_pct,
    EXTRACT(EPOCH FROM (finished_at - started_at))::INTEGER AS duration_seconds,
    triggered_by,
    git_commit_sha,
    started_at,
    finished_at
FROM warehouse.etl_audit_log
ORDER BY started_at DESC;

-- ────────────────────────────────────────────────────────────────────────────
-- STORED PROCEDURE: Truncate all staging tables (for reruns)
-- ────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE PROCEDURE warehouse.sp_clear_staging()
LANGUAGE plpgsql
AS $$
BEGIN
    TRUNCATE TABLE staging.stg_customers CASCADE;
    TRUNCATE TABLE staging.stg_products CASCADE;
    TRUNCATE TABLE staging.stg_sales CASCADE;
    TRUNCATE TABLE staging.stg_rejections CASCADE;
    RAISE NOTICE 'All staging tables cleared.';
END;
$$;

-- ────────────────────────────────────────────────────────────────────────────
-- STORED PROCEDURE: Get last successful run metadata
-- ────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION warehouse.fn_last_successful_run()
RETURNS TABLE (
    audit_id BIGINT,
    batch_date DATE,
    status VARCHAR,
    rows_extracted INTEGER,
    rows_inserted INTEGER,
    finished_at TIMESTAMP
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        al.audit_id,
        al.batch_date,
        al.status,
        al.rows_extracted,
        al.rows_inserted,
        al.finished_at
    FROM warehouse.etl_audit_log al
    WHERE al.status = 'SUCCESS'
      AND al.pipeline_name = 'retail_etl_full'
    ORDER BY al.finished_at DESC
    LIMIT 1;
END;
$$;

-- ────────────────────────────────────────────────────────────────────────────
-- STORED PROCEDURE: Refresh all materialized views
-- ────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE PROCEDURE warehouse.sp_refresh_materialized_views()
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE NOTICE 'Refreshing mv_product_performance...';
    REFRESH MATERIALIZED VIEW CONCURRENTLY warehouse.mv_product_performance;
    
    RAISE NOTICE 'Refreshing mv_customer_ltv...';
    REFRESH MATERIALIZED VIEW CONCURRENTLY warehouse.mv_customer_ltv;
    
    RAISE NOTICE 'Refreshing mv_channel_payment_analysis...';
    REFRESH MATERIALIZED VIEW CONCURRENTLY warehouse.mv_channel_payment_analysis;
    
    RAISE NOTICE 'All materialized views refreshed.';
END;
$$;

-- ────────────────────────────────────────────────────────────────────────────
-- SAMPLE QUERIES for quick validation
-- ────────────────────────────────────────────────────────────────────────────

/*

-- Check schema creation
SELECT schema_name FROM information_schema.schemata WHERE schema_name IN ('staging', 'warehouse');

-- Check tables
SELECT table_name FROM information_schema.tables WHERE table_schema = 'warehouse' ORDER BY table_name;

-- Check views
SELECT table_name FROM information_schema.tables WHERE table_schema = 'warehouse' AND table_type = 'VIEW';

-- Get last successful run
SELECT * FROM warehouse.fn_last_successful_run();

-- View daily DQ summary
SELECT * FROM warehouse.vw_dq_daily_load_summary LIMIT 10;

-- Rejection summary
SELECT * FROM staging.vw_rejection_summary LIMIT 10;

-- Data quality detailed report
SELECT * FROM warehouse.vw_data_quality_detailed LIMIT 20;

-- Pipeline performance metrics
SELECT * FROM warehouse.vw_pipeline_performance LIMIT 10;

-- Top products by revenue
SELECT * FROM warehouse.mv_product_performance ORDER BY total_revenue DESC LIMIT 10;

-- Top customers by LTV
SELECT * FROM warehouse.mv_customer_ltv ORDER BY total_spent DESC LIMIT 10;

*/

-- ============================================================================
-- Schema v2 improvements complete!
-- ============================================================================
-- Materialized views and stored procedures are now ready.
-- Refresh views periodically with: CALL warehouse.sp_refresh_materialized_views();

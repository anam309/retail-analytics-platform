-- ============================================================================
-- Retail Analytics Data Warehouse — PostgreSQL Schema (Phase 1)
-- ============================================================================
-- Creates staging and warehouse schemas with dimensional model and audit logs.
-- Run this first, then run retail_analytics_schema_v2_improvements.sql.
--
-- Schemas:
--   - staging: transient landing zone (stg_customers, stg_products, stg_sales, stg_rejections)
--   - warehouse: dimensional model (dim_customer, dim_product, dim_date, fact_sales, etl_audit_log)
--
-- Prerequisites:
--   - PostgreSQL 12+
--   - Database: retail_analytics
--   - Connection user has CREATE SCHEMA privilege
--
-- ============================================================================

-- Drop existing schemas if they exist (use with caution in production)
-- DROP SCHEMA IF EXISTS warehouse CASCADE;
-- DROP SCHEMA IF EXISTS staging CASCADE;

-- ────────────────────────────────────────────────────────────────────────────
-- SCHEMAS
-- ────────────────────────────────────────────────────────────────────────────

CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS warehouse;

-- ────────────────────────────────────────────────────────────────────────────
-- STAGING SCHEMA — Raw landing zone (transient)
-- ────────────────────────────────────────────────────────────────────────────

-- Staging: Raw customers
CREATE TABLE IF NOT EXISTS staging.stg_customers (
    stg_customer_id  BIGSERIAL PRIMARY KEY,
    customer_id      VARCHAR(50) NOT NULL,
    first_name       VARCHAR(100),
    last_name        VARCHAR(100),
    email            VARCHAR(255),
    phone            VARCHAR(20),
    date_of_birth    DATE,
    address_line1    VARCHAR(255),
    city             VARCHAR(100),
    state            VARCHAR(2),
    country          VARCHAR(100),
    postal_code      VARCHAR(20),
    loyalty_tier     VARCHAR(50),
    customer_segment VARCHAR(50),
    email_opt_in     BOOLEAN,
    sms_opt_in       BOOLEAN,
    registration_date DATE,
    updated_at       TIMESTAMP,
    _source_file     VARCHAR(255),
    created_at       TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stg_customers_customer_id ON staging.stg_customers(customer_id);

-- Staging: Raw products
CREATE TABLE IF NOT EXISTS staging.stg_products (
    stg_product_id   BIGSERIAL PRIMARY KEY,
    product_id       VARCHAR(50) NOT NULL,
    product_name     VARCHAR(255),
    description      TEXT,
    category         VARCHAR(100),
    subcategory      VARCHAR(100),
    brand            VARCHAR(100),
    supplier_name    VARCHAR(255),
    current_price    NUMERIC(12, 2),
    unit_cost        NUMERIC(12, 2),
    weight_kg        NUMERIC(8, 2),
    is_active        BOOLEAN,
    reorder_point    INTEGER,
    created_at       DATE,
    updated_at       DATE,
    _source_file     VARCHAR(255),
    inserted_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stg_products_product_id ON staging.stg_products(product_id);

-- Staging: Raw sales
CREATE TABLE IF NOT EXISTS staging.stg_sales (
    stg_sale_id       BIGSERIAL PRIMARY KEY,
    sale_id           VARCHAR(50) NOT NULL UNIQUE,
    transaction_id    VARCHAR(50),
    line_number       SMALLINT,
    customer_id       VARCHAR(50),
    product_id        VARCHAR(50),
    transaction_date  DATE,
    quantity          INTEGER,
    unit_price        NUMERIC(12, 2),
    discount_amount   NUMERIC(12, 2),
    tax_amount        NUMERIC(12, 2),
    payment_method    VARCHAR(50),
    channel           VARCHAR(50),
    store_id          VARCHAR(20),
    _source_file      VARCHAR(255),
    created_at        TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stg_sales_transaction_id ON staging.stg_sales(transaction_id);
CREATE INDEX IF NOT EXISTS idx_stg_sales_sale_id ON staging.stg_sales(sale_id);

-- Staging: Rejected rows (data quality failures)
CREATE TABLE IF NOT EXISTS staging.stg_rejections (
    rejection_id      BIGSERIAL PRIMARY KEY,
    source_table      VARCHAR(100),
    source_pk         VARCHAR(100),
    rejection_category VARCHAR(50),
    rejection_reason  TEXT,
    batch_date        DATE,
    raw_record        JSONB,
    created_at        TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stg_rejections_batch_date ON staging.stg_rejections(batch_date);
CREATE INDEX IF NOT EXISTS idx_stg_rejections_category ON staging.stg_rejections(rejection_category);

-- ────────────────────────────────────────────────────────────────────────────
-- WAREHOUSE SCHEMA — Dimensional model (analytics)
-- ────────────────────────────────────────────────────────────────────────────

-- Dimension: Customers (SCD Type 2)
CREATE TABLE IF NOT EXISTS warehouse.dim_customer (
    customer_sk      BIGSERIAL PRIMARY KEY,
    customer_id      VARCHAR(50) NOT NULL,
    first_name       VARCHAR(100),
    last_name        VARCHAR(100),
    email            VARCHAR(255),
    phone            VARCHAR(20),
    date_of_birth    DATE,
    address_line1    VARCHAR(255),
    city             VARCHAR(100),
    state            VARCHAR(2),
    country          VARCHAR(100),
    postal_code      VARCHAR(20),
    loyalty_tier     VARCHAR(50),
    customer_segment VARCHAR(50),
    email_opt_in     BOOLEAN,
    sms_opt_in       BOOLEAN,
    last_activity_date DATE,
    registration_date DATE,
    effective_from   DATE NOT NULL,
    effective_to     DATE NOT NULL DEFAULT '9999-12-31',
    is_current       BOOLEAN NOT NULL DEFAULT TRUE,
    scd_hash         VARCHAR(64),
    created_at       TIMESTAMP DEFAULT NOW(),
    updated_at       TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dim_customer_nk ON warehouse.dim_customer(customer_id, is_current);
CREATE INDEX IF NOT EXISTS idx_dim_customer_sk ON warehouse.dim_customer(customer_sk);

-- Dimension: Products (SCD Type 2)
CREATE TABLE IF NOT EXISTS warehouse.dim_product (
    product_sk       BIGSERIAL PRIMARY KEY,
    product_id       VARCHAR(50) NOT NULL,
    product_name     VARCHAR(255),
    description      TEXT,
    category         VARCHAR(100),
    subcategory      VARCHAR(100),
    brand            VARCHAR(100),
    supplier_name    VARCHAR(255),
    current_price    NUMERIC(12, 2),
    unit_cost        NUMERIC(12, 2),
    weight_kg        NUMERIC(8, 2),
    is_active        BOOLEAN,
    reorder_point    INTEGER,
    effective_from   DATE NOT NULL,
    effective_to     DATE NOT NULL DEFAULT '9999-12-31',
    is_current       BOOLEAN NOT NULL DEFAULT TRUE,
    scd_hash         VARCHAR(64),
    created_at       TIMESTAMP DEFAULT NOW(),
    updated_at       TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dim_product_nk ON warehouse.dim_product(product_id, is_current);
CREATE INDEX IF NOT EXISTS idx_dim_product_sk ON warehouse.dim_product(product_sk);

-- Dimension: Date (static, pre-populated)
CREATE TABLE IF NOT EXISTS warehouse.dim_date (
    date_key         INTEGER PRIMARY KEY,  -- YYYYMMDD format
    date_val         DATE NOT NULL UNIQUE,
    day_of_week      VARCHAR(10),
    day_of_month     INTEGER,
    day_of_year      INTEGER,
    week_of_year     INTEGER,
    month            INTEGER,
    month_name       VARCHAR(20),
    quarter          INTEGER,
    fiscal_quarter   INTEGER,
    year             INTEGER,
    fiscal_year      INTEGER,
    is_holiday       BOOLEAN DEFAULT FALSE,
    created_at       TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dim_date_date_val ON warehouse.dim_date(date_val);

-- Fact: Sales transactions
CREATE TABLE IF NOT EXISTS warehouse.fact_sales (
    sale_sk               BIGSERIAL PRIMARY KEY,
    customer_sk           INTEGER NOT NULL DEFAULT -1,
    product_sk            INTEGER NOT NULL DEFAULT -1,
    transaction_date_key  INTEGER,
    transaction_date      DATE,
    transaction_id        VARCHAR(50),
    line_number           SMALLINT,
    quantity              INTEGER,
    unit_price            NUMERIC(12, 2),
    gross_revenue         NUMERIC(14, 2),
    discount_amount       NUMERIC(12, 2),
    net_revenue           NUMERIC(14, 2),
    unit_cost_snapshot    NUMERIC(12, 2),
    cogs                  NUMERIC(14, 2),
    gross_profit          NUMERIC(14, 2),
    tax_amount            NUMERIC(12, 2),
    total_amount          NUMERIC(14, 2),
    payment_method        VARCHAR(50),
    channel               VARCHAR(50),
    store_id              VARCHAR(20),
    _stg_sale_id          VARCHAR(50) UNIQUE,
    created_at            TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_fact_sales_grain UNIQUE (transaction_id, line_number),
    CONSTRAINT fk_fact_sales_customer FOREIGN KEY (customer_sk) REFERENCES warehouse.dim_customer(customer_sk),
    CONSTRAINT fk_fact_sales_product FOREIGN KEY (product_sk) REFERENCES warehouse.dim_product(product_sk),
    CONSTRAINT fk_fact_sales_date FOREIGN KEY (transaction_date_key) REFERENCES warehouse.dim_date(date_key)
);

CREATE INDEX IF NOT EXISTS idx_fact_sales_customer_sk ON warehouse.fact_sales(customer_sk);
CREATE INDEX IF NOT EXISTS idx_fact_sales_product_sk ON warehouse.fact_sales(product_sk);
CREATE INDEX IF NOT EXISTS idx_fact_sales_date_key ON warehouse.fact_sales(transaction_date_key);
CREATE INDEX IF NOT EXISTS idx_fact_sales_transaction_date ON warehouse.fact_sales(transaction_date);
CREATE INDEX IF NOT EXISTS uix_fact_sales_stg_id ON warehouse.fact_sales(_stg_sale_id);

-- ETL Audit Log
CREATE TABLE IF NOT EXISTS warehouse.etl_audit_log (
    audit_id         BIGSERIAL PRIMARY KEY,
    pipeline_name    VARCHAR(100) NOT NULL,
    source_table     VARCHAR(255),
    target_table     VARCHAR(255),
    batch_date       DATE NOT NULL,
    status           VARCHAR(20),  -- RUNNING, SUCCESS, FAILED, PARTIAL
    triggered_by     VARCHAR(50),
    git_commit_sha   VARCHAR(40),
    run_id           UUID,
    rows_extracted   INTEGER DEFAULT 0,
    rows_inserted    INTEGER DEFAULT 0,
    rows_updated     INTEGER DEFAULT 0,
    rows_rejected    INTEGER DEFAULT 0,
    rows_skipped     INTEGER DEFAULT 0,
    error_message    TEXT,
    started_at       TIMESTAMP DEFAULT NOW(),
    finished_at      TIMESTAMP,
    created_at       TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_etl_audit_log_batch_date ON warehouse.etl_audit_log(batch_date);
CREATE INDEX IF NOT EXISTS idx_etl_audit_log_pipeline ON warehouse.etl_audit_log(pipeline_name, status);

-- ────────────────────────────────────────────────────────────────────────────
-- FUNCTION: Populate dim_date (pre-compute calendar dimension)
-- ────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION warehouse.fn_populate_dim_date(
    start_date DATE,
    end_date DATE
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_current_date DATE;
    v_count INTEGER := 0;
BEGIN
    v_current_date := start_date;
    
    WHILE v_current_date <= end_date LOOP
        INSERT INTO warehouse.dim_date (
            date_key, date_val, day_of_week, day_of_month, day_of_year,
            week_of_year, month, month_name, quarter, fiscal_quarter, year, fiscal_year
        )
        VALUES (
            TO_CHAR(v_current_date, 'YYYYMMDD')::INTEGER,
            v_current_date,
            TO_CHAR(v_current_date, 'Day'),
            EXTRACT(DAY FROM v_current_date)::INTEGER,
            EXTRACT(DOY FROM v_current_date)::INTEGER,
            EXTRACT(WEEK FROM v_current_date)::INTEGER,
            EXTRACT(MONTH FROM v_current_date)::INTEGER,
            TO_CHAR(v_current_date, 'Month'),
            EXTRACT(QUARTER FROM v_current_date)::INTEGER,
            CASE WHEN EXTRACT(MONTH FROM v_current_date) >= 4 
                 THEN EXTRACT(QUARTER FROM v_current_date)
                 ELSE EXTRACT(QUARTER FROM v_current_date - INTERVAL '3 months')
            END::INTEGER,
            EXTRACT(YEAR FROM v_current_date)::INTEGER,
            CASE WHEN EXTRACT(MONTH FROM v_current_date) >= 4 
                 THEN EXTRACT(YEAR FROM v_current_date)::INTEGER
                 ELSE (EXTRACT(YEAR FROM v_current_date) - 1)::INTEGER
            END
        )
        ON CONFLICT (date_key) DO NOTHING;
        
        v_count := v_count + 1;
        v_current_date := v_current_date + INTERVAL '1 day';
    END LOOP;
    
    RETURN v_count;
END;
$$;

-- Pre-populate dim_date for 2020–2030
SELECT warehouse.fn_populate_dim_date('2020-01-01'::DATE, '2030-12-31'::DATE);

-- ────────────────────────────────────────────────────────────────────────────
-- VIEW: Data quality summary (daily load)
-- ────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE VIEW warehouse.vw_dq_daily_load_summary AS
SELECT
    DATE(fs.created_at) AS load_date,
    COUNT(*) AS total_rows_loaded,
    SUM(CASE WHEN fs.customer_sk = -1 THEN 1 ELSE 0 END) AS unknown_customer_rows,
    ROUND(
        100.0 * SUM(CASE WHEN fs.customer_sk = -1 THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0),
        2
    ) AS pct_unknown_customers,
    SUM(CASE WHEN fs.product_sk = -1 THEN 1 ELSE 0 END) AS unknown_product_rows,
    ROUND(
        100.0 * SUM(CASE WHEN fs.product_sk = -1 THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0),
        2
    ) AS pct_unknown_products,
    SUM(CASE WHEN fs.gross_profit < 0 THEN 1 ELSE 0 END) AS negative_margin_rows,
    ROUND(
        100.0 * SUM(CASE WHEN fs.gross_profit < 0 THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0),
        2
    ) AS pct_negative_margin,
    SUM(fs.net_revenue) AS total_revenue,
    SUM(fs.cogs) AS total_cogs,
    SUM(fs.gross_profit) AS total_gross_profit
FROM warehouse.fact_sales fs
GROUP BY DATE(fs.created_at)
ORDER BY load_date DESC;

-- ────────────────────────────────────────────────────────────────────────────
-- VIEW: Rejection summary (staging quality metrics)
-- ────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE VIEW staging.vw_rejection_summary AS
SELECT
    batch_date,
    source_table,
    rejection_category,
    COUNT(*) AS rejection_count
FROM staging.stg_rejections
GROUP BY batch_date, source_table, rejection_category
ORDER BY batch_date DESC, rejection_count DESC;

-- ────────────────────────────────────────────────────────────────────────────
-- Permissions (optional: set for non-admin users)
-- ────────────────────────────────────────────────────────────────────────────

-- GRANT USAGE ON SCHEMA staging, warehouse TO etl_user;
-- GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA staging TO etl_user;
-- GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA warehouse TO etl_user;
-- GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA warehouse TO etl_user;

-- ============================================================================
-- Schema creation complete!
-- ============================================================================
-- Next: Run retail_analytics_schema_v2_improvements.sql for enhancements.
-- Then: Generate sample data with: python3 generate_data.py
-- Finally: Run the ETL pipeline.

# Retail Analytics Platform

[![CI](https://github.com/anam309/retail-analytics-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/anam309/retail-analytics-platform/actions/workflows/ci.yml)

A Python + PostgreSQL ETL pipeline that turns raw retail transaction extracts into a dimensional data warehouse — the kind of foundation BI tools (Looker, Power BI, Metabase) sit on top of.

Built to demonstrate the parts of data engineering that portfolio toy projects usually skip: **SCD Type 2 history tracking**, **idempotent reruns**, **a real data-quality framework with a rejection audit trail**, and **full pipeline observability** via an ETL audit log — not just "CSV in, table out."

---

## What it does

```
data/raw/*.csv  →  extract  →  transform  →  load  →  PostgreSQL (staging + warehouse)
```

- **Extract** — reads customer, product, and sales CSVs with zero type coercion (everything lands as `str`), so malformed data fails loudly in `transform`, not silently as a `NaN`.
- **Transform** — validates required fields, coerces types, applies range/business-rule checks, resolves customer/product foreign keys, computes revenue/margin metrics, and hashes each dimension row for change detection.
- **Load** — lands the raw batch in `staging` for audit, upserts `dim_customer`/`dim_product` as **SCD Type 2** (full history, no data loss on updates), extends `dim_date` automatically, bulk-loads `fact_sales` with a dedup pre-filter, and writes every rejected row to `staging.stg_rejections` with the full original record as JSON.
- **Audits itself** — every run writes a row to `warehouse.etl_audit_log` (status, row counts, duration, triggering system, git SHA), which doubles as the high-water mark for incremental loads.

Rows that are *invalid* (bad types, impossible values, future dates) are rejected and logged. Rows that are *valid but reference an unknown customer/product* are **not** rejected — they load with a `-1` sentinel key, because a real sale from an unrecorded customer is still real revenue.

---

## Architecture

```
                 ┌──────────────┐      ┌──────────────┐      ┌──────────────┐
  data/raw/*.csv │   extract    │      │  transform   │      │     load     │
  ─────────────► │  (pandas)    │ ───► │  (pandas)    │ ───► │ (SQLAlchemy) │
                 └──────────────┘      └──────────────┘      └──────┬───────┘
                                                                     │
                        ┌────────────────────────────────────────────┘
                        ▼
        ┌───────────────────────────────┐      ┌────────────────────────────────────┐
        │   staging (landing zone)      │      │   warehouse (star schema)          │
        │  stg_customers, stg_products, │      │  dim_customer, dim_product (SCD2)  │
        │  stg_sales, stg_rejections    │ ───► │  dim_date, fact_sales               │
        │                                │      │  etl_audit_log                     │
        └───────────────────────────────┘      └────────────────────────────────────┘
```

An interactive version of this diagram is in [`etl_architecture.html`](etl_architecture.html) — open it in a browser.

---

## Quickstart

Requires Docker (for Postgres) and Python 3.10+.

```bash
# 1. Start Postgres and bootstrap the schema (staging + warehouse, both schema files applied automatically)
docker compose up -d

# 2. Install dependencies
pip install -r requirements.txt

# 3. Generate reproducible sample data (500 customers, 100 products, 10,000 sales)
python generate_data.py

# 4. Run the pipeline
python -m etl.run

# 5. Generate business reports (CSVs + an HTML summary) from the warehouse
python -m reports.generate
```

Expected output on a fresh database:

```
[extract] Complete — 10600 total rows across 3 files
[transform] customers  clean=500  rejected=0
[transform] products   clean=100  rejected=0
[load] dim_customer          inserted=500  updated=0  skipped=0
[load] dim_product           inserted=100  updated=0  skipped=0
[transform] sales      clean=10000  rejected=0  unknown_cust=0  unknown_prod=0
[load] fact_sales            inserted=10000  skipped=0
[run] Pipeline finished successfully
```

Rerun `python -m etl.run` again with no changes and it's a no-op on `fact_sales`/dimensions (idempotent) but re-lands the batch snapshot in `staging`.

To point at your own database instead of the Docker one:

```bash
DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/db python -m etl.run
```

To reprocess a specific historical date:

```bash
BATCH_DATE=2024-03-15 python -m etl.run
```

---

## Data model

Star schema: two SCD Type 2 dimensions, one static date dimension, one fact table.

| Table | Type | Notes |
|---|---|---|
| `dim_customer` | SCD2 dimension | Full history on name/contact/address/loyalty-tier changes. Natural key `customer_id`, surrogate `customer_sk`. |
| `dim_product` | SCD2 dimension | Full history on name/category/price/cost changes. Natural key `product_id`, surrogate `product_sk`. |
| `dim_date` | Static dimension | Pre-populated 2020–2030, auto-extends if a transaction date falls outside that range. |
| `fact_sales` | Fact table | One row per `(transaction_id, line_number)`. Pre-computed revenue, cost, and margin. |
| `etl_audit_log` | Operational | Every run's status, row counts, duration, and git SHA. |

---

## Data quality

Every transform stage classifies failures into one of six categories (`TYPE_ERROR`, `NULL_VIOLATION`, `RANGE_CHECK`, `BUSINESS_RULE`, `DUPLICATE`, `REF_INTEGRITY`) and writes the full source row to `staging.stg_rejections` as JSON — nothing is silently dropped. Query it directly, or use the built-in views:

```sql
SELECT * FROM warehouse.vw_dq_daily_load_summary;   -- daily volume, revenue, unknown-key %, negative-margin %
SELECT * FROM staging.vw_rejection_summary;         -- rejections by batch/table/category
```

Configurable thresholds in [`config/settings.py`](config/settings.py) log a warning (not a hard failure) when breached — e.g. more than 5% of a batch's sales referencing an unrecognized customer.

---

## Business reporting

The warehouse schema already carries three materialized views built for exactly this: `mv_product_performance`, `mv_customer_ltv`, and `mv_channel_payment_analysis`. Every ETL run refreshes them (`etl.load.refresh_reporting_views`, called from `run_pipeline`), so they're never more stale than the last successful load.

[`reports/`](reports/) is a thin reporting layer on top:

- **`reports/queries.py`** — five report functions (monthly revenue trend, top products by revenue, top customers by lifetime value, channel/payment performance, data-quality summary), each returning a plain pandas DataFrame. This is exactly what a BI tool like Power BI or Looker would query directly instead — the views exist independently of this script.
- **`reports/charts.py`** — hand-rolled SVG bar/line charts (no charting library dependency), following a fixed categorical color order and validated palette, with a hover tooltip and crosshair on the trend line.
- **`reports/generate.py`** — a CLI (`python -m reports.generate`) that runs all five reports and writes one CSV each, plus a single `business_report.html` with charts alongside the tables, to `reports/output/` (gitignored — it's generated, not source).

`business_report.html` is the client-facing artifact: revenue/profit trend line, top-10 product and customer bar charts, and channel performance, each with the full data table underneath so nothing is chart-only.

```sql
-- Point Power BI / Looker / any SQL client at these directly:
SELECT * FROM warehouse.mv_product_performance ORDER BY total_revenue DESC;
SELECT * FROM warehouse.mv_customer_ltv ORDER BY total_spent DESC;
SELECT * FROM warehouse.mv_channel_payment_analysis;
```

---

## Testing

```bash
pip install -r requirements.txt
pytest tests/ -v
```

27 tests: pure-function unit tests for `transform_customers`/`transform_products`/`reports.charts` (no database needed), and integration tests against a real Postgres instance for FK resolution, SCD2 versioning, fact dedup, materialized-view refresh, business report queries, and full end-to-end pipeline runs — including regression tests for real bugs caught during development (see below).

Integration tests look for `TEST_DATABASE_URL` (defaults to `postgresql+psycopg2://postgres:password@localhost:5432/retail_analytics_test`) and skip automatically if no database is reachable, so the unit-test subset always runs.

CI (`.github/workflows/ci.yml`) runs the full suite against a throwaway Postgres service on every push, then does a real end-to-end run of the pipeline against a fresh database as a smoke test.

---

## Notable bugs caught along the way

Worth calling out because these only show up when you actually run the pipeline against a real database, not just read the code:

1. **SCD2 upsert inserted columns that don't exist on the target table.** `extract.py` tags every row with `_source_file` for provenance; the generic `_scd2_upsert()` in `load.py` was inserting that column straight into `dim_customer`/`dim_product`, which have no such column — every dimension load failed before anything committed. Fixed by filtering the insert to the destination table's actual columns (`etl/load.py`).
2. **`fact_sales`'s FK sentinel (`-1` for "unknown customer/product") had no matching row to reference.** The FK constraints require `-1` to exist in `dim_customer`/`dim_product`; nothing seeded it, so every sale with an unresolved customer or product threw `ForeignKeyViolation`. Fixed by seeding an `UNKNOWN` sentinel row in both dimensions (`retail_analytics_schema.sql`).
3. **Same-batch FK resolution ordering.** `transform_sales` resolves customer/product surrogate keys by querying the dimensions — but the pipeline used to transform sales *before* loading that batch's own dimension rows, so a customer's first-ever purchase in the same batch as their first-ever registration always resolved to `-1`. Fixed by reordering `run_pipeline` to load dimensions first (`etl/load.py`).
4. **Non-ASCII characters in log/print output crashed on Windows.** `generate_data.py` and the ETL modules used `→`/box-drawing characters in `print()`/`log.info()` calls; Windows consoles default to the `cp1252` codepage, which can't encode them, so the script crashed with `UnicodeEncodeError` before finishing. Replaced with plain ASCII (`generate_data.py`, `etl/extract.py`, `etl/load.py`, `etl/run.py`).
5. **`mv_channel_payment_analysis` had no unique index.** `REFRESH MATERIALIZED VIEW CONCURRENTLY` requires one; without it, `warehouse.sp_refresh_materialized_views()` failed outright the first time anything actually called it, which nothing had until the reporting layer was wired up. Fixed by adding a unique index on `(channel, payment_method, month)` (`retail_analytics_schema_v2_improvements.sql`).

Regression tests for bugs 1, 2, 3, and 5 live in `tests/test_load.py`, `tests/test_pipeline_integration.py`, and `tests/test_reports.py`.

---

## Tech stack

Python 3.10+ · pandas 2.x · SQLAlchemy 2.x · PostgreSQL 12+ · psycopg2 · pytest · Docker Compose · GitHub Actions

---

## Repository layout

```
config/settings.py          Central config — DB URL, paths, DQ thresholds, batch date
etl/extract.py               Stage 1 — CSV → raw DataFrames
etl/transform.py             Stage 2 — validate, coerce, hash, resolve FKs
etl/load.py                  Stage 3 — SCD2 upserts, bulk inserts, audit logging
etl/run.py                   CLI entrypoint (`python -m etl.run`)
reports/queries.py            Business report queries (revenue trend, top products/customers, ...)
reports/charts.py              Hand-rolled SVG bar/line chart generation, no library dependency
reports/generate.py           CLI entrypoint (`python -m reports.generate`) — CSVs + HTML summary with charts
generate_data.py             Reproducible sample data generator (seeded, Faker)
retail_analytics_schema.sql              Schema part 1 — tables, seed sentinel rows
retail_analytics_schema_v2_improvements.sql  Schema part 2 — audit log, DQ views, procedures
tests/                        pytest suite (unit + integration)
docker-compose.yml            One-command local Postgres + schema bootstrap
.github/workflows/ci.yml       CI: tests + end-to-end smoke run
```
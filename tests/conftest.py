"""
tests/conftest.py — shared fixtures for the ETL test suite.

Unit tests (test_transform_customers.py, test_transform_products.py) need no
database. Integration tests (test_transform_sales.py, test_load.py,
test_pipeline_integration.py) need a live Postgres reachable via
TEST_DATABASE_URL — they are skipped automatically if none is reachable.
"""

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg2://postgres:password@localhost:5432/retail_analytics_test",
)

REPO_ROOT = Path(__file__).parent.parent
SCHEMA_FILES = [
    REPO_ROOT / "retail_analytics_schema.sql",
    REPO_ROOT / "retail_analytics_schema_v2_improvements.sql",
]


@pytest.fixture(scope="session")
def engine():
    """A session-scoped engine pointed at a freshly-built schema.

    Skips the whole test session if no test database is reachable, so the
    unit-test-only subset of the suite still runs in environments without
    Postgres available.
    """
    eng = create_engine(TEST_DB_URL)
    try:
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"No reachable test database at {TEST_DB_URL}: {exc}")

    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS staging CASCADE"))
        conn.execute(text("DROP SCHEMA IF EXISTS warehouse CASCADE"))

    for path in SCHEMA_FILES:
        with eng.begin() as conn:
            conn.execute(text(path.read_text()))

    return eng


@pytest.fixture
def db(engine):
    """A cleaned database connection for integration tests.

    Not autouse: only tests that actually declare this fixture (or `engine`)
    trigger a database connection attempt, so the DB-free unit tests
    (test_transform_customers.py, test_transform_products.py) never touch
    Postgres at all.
    """
    with engine.begin() as conn:
        conn.execute(text("""
            TRUNCATE TABLE
                staging.stg_customers, staging.stg_products, staging.stg_sales,
                staging.stg_rejections, warehouse.fact_sales, warehouse.etl_audit_log
            CASCADE
        """))
        conn.execute(text("DELETE FROM warehouse.dim_customer WHERE customer_sk != -1"))
        conn.execute(text("DELETE FROM warehouse.dim_product WHERE product_sk != -1"))
    return engine

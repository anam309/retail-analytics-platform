import pandas as pd

from etl.transform import transform_products


def _df(rows):
    return pd.DataFrame(rows, dtype=str).fillna("")


def test_valid_row_passes_through():
    df = _df([{
        "product_id": "PROD-1", "product_name": "Widget", "description": "A widget",
        "category": "Tools", "subcategory": "Hand Tools", "brand": "Acme",
        "supplier_name": "Acme Supply", "current_price": "19.99", "unit_cost": "8.00",
        "weight_kg": "0.5", "is_active": "true", "reorder_point": "10",
        "created_at": "2020-01-01", "updated_at": "2020-01-01",
    }])

    clean, rejected = transform_products(df)

    assert len(clean) == 1
    assert rejected.empty
    assert clean.iloc[0]["current_price"] == 19.99
    assert clean.iloc[0]["is_active"] == True


def test_negative_price_is_rejected():
    df = _df([{
        "product_id": "PROD-2", "product_name": "Bad", "category": "Tools",
        "current_price": "-5.00", "unit_cost": "2.00",
    }])

    clean, rejected = transform_products(df)

    assert clean.empty
    assert rejected.iloc[0]["rejection_category"] == "RANGE_CHECK"


def test_non_numeric_price_is_rejected():
    df = _df([{
        "product_id": "PROD-3", "product_name": "Bad", "category": "Tools",
        "current_price": "N/A", "unit_cost": "2.00",
    }])

    clean, rejected = transform_products(df)

    assert clean.empty
    assert rejected.iloc[0]["rejection_category"] == "TYPE_ERROR"


def test_missing_reorder_point_defaults_to_ten():
    df = _df([{
        "product_id": "PROD-4", "product_name": "Widget", "category": "Tools",
        "current_price": "9.99", "unit_cost": "4.00", "reorder_point": "",
    }])

    clean, _ = transform_products(df)

    assert clean.iloc[0]["reorder_point"] == 10

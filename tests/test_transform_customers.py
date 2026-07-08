import pandas as pd

from etl.transform import transform_customers


def _df(rows):
    return pd.DataFrame(rows, dtype=str).fillna("")


def test_valid_row_passes_through():
    df = _df([{
        "customer_id": "CUST-1", "first_name": "Ada", "last_name": "Lovelace",
        "email": "ada@example.com", "phone": "555-0100",
        "date_of_birth": "1990-01-01", "address_line1": "1 Main St",
        "city": "Springfield", "state": "IL", "country": "USA",
        "postal_code": "62701", "loyalty_tier": "Gold", "customer_segment": "Regular",
        "email_opt_in": "true", "sms_opt_in": "false",
        "registration_date": "2020-01-01", "updated_at": "2020-01-01",
    }])

    clean, rejected = transform_customers(df)

    assert len(clean) == 1
    assert rejected.empty
    assert clean.iloc[0]["email_opt_in"] == True
    assert clean.iloc[0]["sms_opt_in"] == False
    assert clean.iloc[0]["scd_hash"]


def test_missing_required_field_is_rejected():
    df = _df([{
        "customer_id": "CUST-2", "first_name": "", "last_name": "Smith",
        "email": "a@b.com",
    }])

    clean, rejected = transform_customers(df)

    assert clean.empty
    assert len(rejected) == 1
    assert rejected.iloc[0]["rejection_category"] == "NULL_VIOLATION"
    assert rejected.iloc[0]["source_pk"] == "CUST-2"


def test_scd_hash_changes_when_tracked_field_changes():
    base = {
        "customer_id": "CUST-3", "first_name": "Ada", "last_name": "Lovelace",
        "email": "a@b.com", "city": "Springfield",
    }
    hash_before = transform_customers(_df([base]))[0].iloc[0]["scd_hash"]
    hash_after = transform_customers(_df([{**base, "city": "Chicago"}]))[0].iloc[0]["scd_hash"]

    assert hash_before != hash_after


def test_scd_hash_unaffected_by_type1_field_change():
    base = {
        "customer_id": "CUST-4", "first_name": "Ada", "last_name": "Lovelace",
        "email": "a@b.com", "email_opt_in": "true",
    }
    hash_before = transform_customers(_df([base]))[0].iloc[0]["scd_hash"]
    hash_after = transform_customers(_df([{**base, "email_opt_in": "false"}]))[0].iloc[0]["scd_hash"]

    assert hash_before == hash_after

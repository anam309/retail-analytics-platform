"""
generate_data.py — Retail Analytics Sample Data Generator

Generates realistic sample CSVs seeded for reproducibility.
All IDs and FK relationships are consistent across files.

Usage:
    python3 generate_data.py
    python3 generate_data.py --n-customers 1000 --n-sales 50000
"""

import argparse
import random
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from faker import Faker

# ── Seeding ───────────────────────────────────────────────────────────────────

SEED = 42
random.seed(SEED)
np.random.seed(SEED)
fake = Faker("en_US")
Faker.seed(SEED)

OUT_DIR = Path("data/raw")
OUT_DIR.mkdir(parents=True, exist_ok=True)


# ── Product catalog ───────────────────────────────────────────────────────────
# (category, subcategory, brand, name_variants, price_lo, price_hi, cost_pct_lo, cost_pct_hi)

CATALOG = [
    ("Electronics",       "Smartphones",        "TechCore",      ["Pro X1", "Ultra 12", "Vision Max", "Lite 5"],          299.99, 1199.99, 0.48, 0.62),
    ("Electronics",       "Smartphones",        "NovaPixel",     ["Galaxy S", "Edge Pro", "Nano Fold"],                    349.99,  999.99, 0.45, 0.60),
    ("Electronics",       "Laptops",            "ProBook",       ["Elite 15", "Air 13", "Studio Pro", "Flex 360"],         499.99, 1799.99, 0.50, 0.65),
    ("Electronics",       "Laptops",            "CloudSlate",    ["X1 Carbon", "Slim 14", "WorkStation Pro"],              549.99, 1499.99, 0.50, 0.63),
    ("Electronics",       "Headphones",         "SoundWave",     ["ANC 700", "Pro 3", "Bass Plus", "Studio Plus"],          29.99,  349.99, 0.35, 0.55),
    ("Electronics",       "Smart Home",         "SmartHub",      ["Hub Connect", "Mini Dot", "Thermostat Plus"],            24.99,  249.99, 0.40, 0.58),
    ("Clothing",          "Men's Tops",         "UrbanThread",   ["Slim Fit Shirt", "Cotton Polo", "Casual Tee"],           19.99,   89.99, 0.30, 0.48),
    ("Clothing",          "Women's Tops",       "ChicLine",      ["Wrap Blouse", "Linen Shirt", "Silk Top", "Casual Tee"], 24.99,   99.99, 0.30, 0.48),
    ("Clothing",          "Footwear",           "StepSmart",     ["Running Shoe", "Casual Sneaker", "Leather Boot"],        39.99,  189.99, 0.38, 0.55),
    ("Clothing",          "Outerwear",          "WeatherShield", ["Winter Jacket", "Rain Coat", "Fleece Hoodie"],           49.99,  299.99, 0.40, 0.55),
    ("Home & Garden",     "Kitchen",            "ChefsPro",      ["Non-Stick Pan", "Chef Knife Set", "Coffee Maker"],       14.99,  199.99, 0.40, 0.58),
    ("Home & Garden",     "Garden Tools",       "GreenThumb",    ["Pruning Shears", "Garden Hose 50ft", "Trowel Set"],       9.99,   89.99, 0.40, 0.55),
    ("Home & Garden",     "Storage",            "OrderPro",      ["Storage Bin 3-Pack", "Drawer Organiser", "Shelf Unit"],  12.99,  149.99, 0.40, 0.55),
    ("Sports & Outdoors", "Exercise",           "FitForce",      ["Resistance Band Set", "Yoga Mat", "Dumbbell 20lb"],      14.99,  499.99, 0.40, 0.58),
    ("Sports & Outdoors", "Outdoor Recreation", "TrailBlazer",   ["Hiking Backpack", "Camping Tent 2P", "Sleeping Bag"],    29.99,  349.99, 0.42, 0.58),
    ("Beauty",            "Skincare",           "PureGlow",      ["Daily Moisturiser", "SPF 50 Sunscreen", "Retinol Serum"], 12.99,  89.99, 0.30, 0.50),
    ("Beauty",            "Haircare",           "LuxHair",       ["Repair Shampoo", "Deep Conditioner", "Hair Serum"],       9.99,   49.99, 0.30, 0.50),
    ("Books",             "Fiction",            "Horizon Press", ["The Last Signal", "Beyond the Reef", "Ember Rising"],     7.99,   24.99, 0.25, 0.42),
    ("Books",             "Non-Fiction",        "KnowledgeCo",   ["Systems Thinking", "Data at Scale", "Deep Work"],         9.99,   34.99, 0.25, 0.42),
    ("Food & Beverage",   "Supplements",        "VitaCore",      ["Whey Protein 2lb", "BCAA Powder", "Omega-3 Capsules"],   19.99,   89.99, 0.35, 0.52),
]

SUPPLIERS = {
    "TechCore": "TechCore Distribution Ltd",     "NovaPixel": "NovaPixel Direct",
    "ProBook": "ProBook Components Inc",          "CloudSlate": "CloudSlate Supply Co",
    "SoundWave": "SoundWave Audio Ltd",           "SmartHub": "SmartHub Networks",
    "UrbanThread": "Urban Textile Suppliers",     "ChicLine": "ChicLine Fashion Import",
    "StepSmart": "StepSmart Footwear Ltd",        "WeatherShield": "WeatherShield Apparel",
    "ChefsPro": "ChefsPro Kitchenware",           "GreenThumb": "GreenThumb Garden Co",
    "OrderPro": "OrderPro Storage Solutions",     "FitForce": "FitForce Sports Goods",
    "TrailBlazer": "TrailBlazer Outdoor Supply",  "PureGlow": "PureGlow Beauty Imports",
    "LuxHair": "LuxHair Professional",            "Horizon Press": "Horizon Press Distribution",
    "KnowledgeCo": "KnowledgeCo Publishing",      "VitaCore": "VitaCore Nutrition Inc",
}


# ── Generators ────────────────────────────────────────────────────────────────

def generate_products(n: int = 100) -> pd.DataFrame:
    rows = []
    pid = 1
    slots_per_entry = max(1, n // len(CATALOG))

    for cat, subcat, brand, names, p_lo, p_hi, c_lo, c_hi in CATALOG:
        count = slots_per_entry if len(rows) + slots_per_entry <= n else n - len(rows)
        for i in range(count):
            name = names[i % len(names)]
            price = round(random.uniform(p_lo, p_hi), 2)
            cost  = round(price * random.uniform(c_lo, c_hi), 2)
            rows.append({
                "product_id":    f"PROD-{pid:04d}",
                "product_name":  f"{brand} {name}",
                "description":   f"High-quality {name.lower()} by {brand}.",
                "category":      cat,
                "subcategory":   subcat,
                "brand":         brand,
                "supplier_name": SUPPLIERS.get(brand, f"{brand} Supply Co"),
                "current_price": price,
                "unit_cost":     cost,
                "weight_kg":     round(random.uniform(0.1, 15.0), 2),
                "is_active":     random.random() > 0.04,
                "reorder_point": random.randint(5, 50),
                "created_at":    fake.date_between(date(2019, 1, 1), date(2020, 12, 31)).isoformat(),
                "updated_at":    fake.date_between(date(2021, 1, 1), date(2024, 6, 30)).isoformat(),
            })
            pid += 1
        if len(rows) >= n:
            break

    # Pad to exactly n
    while len(rows) < n:
        price = round(random.uniform(9.99, 299.99), 2)
        rows.append({
            "product_id":    f"PROD-{pid:04d}",
            "product_name":  f"StoreBrand Essential {pid}",
            "description":   "General merchandise item.",
            "category":      "General",
            "subcategory":   "Misc",
            "brand":         "StoreBrand",
            "supplier_name": "Generic Wholesale Ltd",
            "current_price": price,
            "unit_cost":     round(price * random.uniform(0.38, 0.58), 2),
            "weight_kg":     round(random.uniform(0.2, 3.0), 2),
            "is_active":     True,
            "reorder_point": random.randint(10, 30),
            "created_at":    fake.date_between(date(2019, 1, 1), date(2020, 12, 31)).isoformat(),
            "updated_at":    fake.date_between(date(2021, 1, 1), date(2024, 6, 30)).isoformat(),
        })
        pid += 1

    return pd.DataFrame(rows[:n])


def generate_customers(n: int = 500) -> pd.DataFrame:
    TIERS    = ["Bronze",  "Silver", "Gold",  "Platinum"]
    T_WGTS   = [0.50,      0.30,     0.15,    0.05]
    SEGMENTS = ["New",     "Regular", "High Value", "At Risk", "Churned"]
    S_WGTS   = [0.15,      0.40,      0.20,        0.15,       0.10]
    DOMAINS  = ["gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com"]

    rows = []
    for i in range(1, n + 1):
        first    = fake.first_name()
        last     = fake.last_name()
        email    = f"{first.lower()}.{last.lower()}{random.randint(1,99)}@{random.choice(DOMAINS)}"
        reg_date = fake.date_between(date(2020, 1, 1), date(2024, 6, 30))
        rows.append({
            "customer_id":       f"CUST-{i:05d}",
            "first_name":        first,
            "last_name":         last,
            "email":             email,
            "phone":             fake.numerify("(###) ###-####"),
            "date_of_birth":     fake.date_of_birth(minimum_age=18, maximum_age=72).isoformat(),
            "address_line1":     fake.street_address(),
            "city":              fake.city(),
            "state":             fake.state_abbr(),
            "country":           "US",
            "postal_code":       fake.zipcode(),
            "loyalty_tier":      random.choices(TIERS,    T_WGTS)[0],
            "customer_segment":  random.choices(SEGMENTS, S_WGTS)[0],
            "email_opt_in":      random.random() > 0.18,
            "sms_opt_in":        random.random() > 0.42,
            "registration_date": reg_date.isoformat(),
            "updated_at":        fake.date_between(reg_date, date(2024, 12, 31)).isoformat(),
        })
    return pd.DataFrame(rows)


def generate_sales(
    n: int = 10_000,
    customer_ids: list = None,
    products_df: pd.DataFrame = None,
) -> pd.DataFrame:
    PAYMENT  = ["Credit Card", "Debit Card", "Cash",  "PayPal", "Apple Pay"]
    P_WGTS   = [0.40,          0.25,         0.10,    0.15,     0.10]
    CHANNELS = ["In-Store",    "Online",     "Mobile App"]
    C_WGTS   = [0.45,          0.35,         0.20]
    STORES   = [f"STORE-{i:03d}" for i in range(1, 11)]

    prod_ids    = products_df["product_id"].tolist()
    price_map   = products_df.set_index("product_id")["current_price"].to_dict()

    # Realistic sampling: popular customers buy more often
    cust_weights = np.random.dirichlet(np.ones(len(customer_ids)) * 0.5)
    # Cheaper products sell more often
    p_weights = np.array([1.0 / (price_map.get(p, 100) ** 0.25) for p in prod_ids], dtype=float)
    p_weights /= p_weights.sum()

    rows      = []
    sale_num  = 1
    txn_num   = 1

    while len(rows) < n:
        n_lines  = random.choices([1, 2, 3], weights=[0.65, 0.25, 0.10])[0]
        txn_id   = f"TXN-{txn_num:07d}"
        cust_id  = random.choices(customer_ids, cust_weights)[0]
        txn_date = fake.date_between(date(2022, 1, 1), date(2024, 12, 31))
        channel  = random.choices(CHANNELS, C_WGTS)[0]
        payment  = random.choices(PAYMENT,  P_WGTS)[0]
        store_id = random.choice(STORES) if channel == "In-Store" else ""

        chosen_prods = np.random.choice(
            prod_ids,
            size=min(n_lines, len(prod_ids)),
            replace=False,
            p=p_weights,
        ).tolist()

        for line, prod_id in enumerate(chosen_prods, start=1):
            base_price = price_map[prod_id]
            unit_price = round(base_price * random.uniform(0.97, 1.03), 2)
            quantity   = random.choices([1, 2, 3, 4, 5], weights=[0.60, 0.20, 0.10, 0.06, 0.04])[0]
            gross      = round(unit_price * quantity, 2)
            disc_pct   = random.choices([0, 0.05, 0.10, 0.15, 0.20], weights=[0.55, 0.20, 0.15, 0.07, 0.03])[0]
            discount   = round(gross * disc_pct, 2)
            net        = round(gross - discount, 2)
            tax        = round(net * random.uniform(0.06, 0.10), 2)

            rows.append({
                "sale_id":          f"STG-{sale_num:07d}",
                "transaction_id":   txn_id,
                "line_number":      line,
                "customer_id":      cust_id,
                "product_id":       prod_id,
                "transaction_date": txn_date.isoformat(),
                "quantity":         quantity,
                "unit_price":       unit_price,
                "discount_amount":  discount,
                "tax_amount":       tax,
                "payment_method":   payment,
                "channel":          channel,
                "store_id":         store_id,
            })
            sale_num += 1
            if len(rows) >= n:
                break

        txn_num += 1

    return pd.DataFrame(rows[:n])


# ── Main ──────────────────────────────────────────────────────────────────────

def main(n_customers: int = 500, n_products: int = 100, n_sales: int = 10_000):
    print(f"Seed: {SEED} — all outputs are reproducible.\n")

    print(f"  Generating {n_products} products ...", end=" ", flush=True)
    products_df = generate_products(n_products)
    products_df.to_csv(OUT_DIR / "products.csv", index=False)
    print(f"done → {OUT_DIR / 'products.csv'}")

    print(f"  Generating {n_customers} customers ...", end=" ", flush=True)
    customers_df = generate_customers(n_customers)
    customers_df.to_csv(OUT_DIR / "customers.csv", index=False)
    print(f"done → {OUT_DIR / 'customers.csv'}")

    print(f"  Generating {n_sales:,} sales records ...", end=" ", flush=True)
    sales_df = generate_sales(
        n_sales,
        customer_ids=customers_df["customer_id"].tolist(),
        products_df=products_df,
    )
    sales_df.to_csv(OUT_DIR / "sales.csv", index=False)
    print(f"done → {OUT_DIR / 'sales.csv'}")

    print("\n── Summary ─────────────────────────────────────────")
    for name, df in [("customers", customers_df), ("products", products_df), ("sales", sales_df)]:
        print(f"  {name+'.csv':<15} {len(df):>7,} rows  |  {df.shape[1]} columns")

    print(f"\n  Unique transactions in sales: {sales_df['transaction_id'].nunique():,}")
    print(f"  Date range:                   {sales_df['transaction_date'].min()} → {sales_df['transaction_date'].max()}")
    print(f"  Total gross revenue:          ${(sales_df['quantity'] * sales_df['unit_price']).sum():>12,.2f}")
    print(f"\n  Output directory: {OUT_DIR.resolve()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate retail analytics sample data")
    parser.add_argument("--n-customers", type=int, default=500)
    parser.add_argument("--n-products",  type=int, default=100)
    parser.add_argument("--n-sales",     type=int, default=10_000)
    args = parser.parse_args()
    main(args.n_customers, args.n_products, args.n_sales)

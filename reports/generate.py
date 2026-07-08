"""
reports/generate.py — CLI entrypoint for business reporting.

Usage:
    python -m reports.generate

Exports one CSV per report plus a single HTML summary to reports/output/,
built from the warehouse's business-facing views and materialized views.
Run this after `python -m etl.run` (the ETL run already refreshes the
underlying materialized views — see etl.load.refresh_reporting_views —
so these reports reflect the latest load).
"""

import logging
from pathlib import Path

from sqlalchemy import create_engine

from config.settings import DB_URL
from reports.queries import (
    channel_payment_performance,
    data_quality_summary,
    monthly_revenue_trend,
    top_customers_by_ltv,
    top_products_by_revenue,
)

log = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).parent / "output"

REPORT_TITLES = {
    "monthly_revenue_trend": "Monthly Revenue Trend",
    "top_products_by_revenue": "Top 10 Products by Revenue",
    "top_customers_by_ltv": "Top 10 Customers by Lifetime Value",
    "channel_payment_performance": "Channel & Payment Method Performance",
    "data_quality_summary": "Data Quality Summary (last 30 loads)",
}


def _html_table(title: str, df) -> str:
    if df.empty:
        return f"<h2>{title}</h2><p><em>No data yet.</em></p>"
    return f"<h2>{title}</h2>{df.to_html(index=False, float_format='{:,.2f}'.format)}"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s %(message)s")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    engine = create_engine(DB_URL)

    reports = {
        "monthly_revenue_trend": monthly_revenue_trend(engine),
        "top_products_by_revenue": top_products_by_revenue(engine),
        "top_customers_by_ltv": top_customers_by_ltv(engine),
        "channel_payment_performance": channel_payment_performance(engine),
        "data_quality_summary": data_quality_summary(engine),
    }

    for name, df in reports.items():
        csv_path = OUTPUT_DIR / f"{name}.csv"
        df.to_csv(csv_path, index=False)
        log.info("[reports] %-28s %4d rows -> %s", name, len(df), csv_path.name)

    html = [
        "<html><head><meta charset='utf-8'><title>Retail Analytics - Business Report</title>",
        "<style>body{font-family:sans-serif;margin:2rem;} "
        "table{border-collapse:collapse;margin-bottom:2rem;} "
        "th,td{border:1px solid #ccc;padding:6px 10px;text-align:right;} "
        "th{background:#f0f0f0;} td:first-child,th:first-child{text-align:left;}</style>"
        "</head><body>",
        "<h1>Retail Analytics - Business Report</h1>",
    ]
    for name, df in reports.items():
        html.append(_html_table(REPORT_TITLES[name], df))
    html.append("</body></html>")

    html_path = OUTPUT_DIR / "business_report.html"
    html_path.write_text("\n".join(html), encoding="utf-8")
    log.info("[reports] HTML summary -> %s", html_path)


if __name__ == "__main__":
    main()

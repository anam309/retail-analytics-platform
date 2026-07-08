"""
reports/generate.py — CLI entrypoint for business reporting.

Usage:
    python -m reports.generate

Exports one CSV per report plus a single HTML summary (with charts) to
reports/output/, built from the warehouse's business-facing views and
materialized views. Run this after `python -m etl.run` (the ETL run already
refreshes the underlying materialized views — see
etl.load.refresh_reporting_views — so these reports reflect the latest load).
"""

import logging
from pathlib import Path

from sqlalchemy import create_engine

from config.settings import DB_URL
from reports.charts import CATEGORICAL, bar_chart, fmt_money, line_chart
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

PAGE_STYLE = """
body { font-family: -apple-system, "Segoe UI", Roboto, Arial, sans-serif; margin: 2.5rem;
       color: #0b0b0b; background: #f9f9f7; }
h1 { margin-bottom: 0.25rem; }
.subtitle { color: #52514e; margin-top: 0; margin-bottom: 2.5rem; }
.report { background: #fcfcfb; border: 1px solid #e1e0d9; border-radius: 6px;
          padding: 1.5rem 1.75rem; margin-bottom: 2rem; }
.report h2 { margin-top: 0; font-size: 1.15rem; }
table { border-collapse: collapse; margin-top: 1rem; width: 100%; font-size: 13.5px; }
th, td { border-bottom: 1px solid #e1e0d9; padding: 6px 10px; text-align: right;
         font-variant-numeric: tabular-nums; }
th { color: #52514e; font-weight: 600; }
td:first-child, th:first-child { text-align: left; font-variant-numeric: normal; }

/* Chart chrome */
.chart-empty { color: #898781; font-style: italic; }
.chart-label { font-size: 12px; fill: #52514e; }
.chart-value { font-size: 12px; fill: #0b0b0b; }
.chart-baseline { stroke: #c3c2b7; stroke-width: 1; }
.chart-grid { stroke: #e1e0d9; stroke-width: 1; }
.chart-tick { font-size: 11px; fill: #898781; }
.chart-line { fill: none; stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
.chart-endlabel { font-size: 12px; font-weight: 600; fill: #0b0b0b; }
.chart-crosshair { stroke: #c3c2b7; stroke-width: 1; opacity: 0; pointer-events: none; }
.chart-hit { fill: transparent; }
.chart-bar path { transition: opacity .1s ease; }
.chart-bar:hover path, .chart-bar:focus path { opacity: 0.7; }
.chart-bar:focus { outline: none; }
.chart-legend { display: flex; gap: 16px; margin-bottom: 4px; font-size: 12px; color: #52514e; }
.legend-item { display: flex; align-items: center; gap: 6px; }
.legend-swatch { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }
.chart-tooltip {
  position: fixed; pointer-events: none; background: #0b0b0b; color: #fff;
  font-size: 12.5px; padding: 6px 10px; border-radius: 4px; opacity: 0;
  transform: translate(-50%, -100%); transition: opacity .1s ease; z-index: 100;
  white-space: nowrap;
}
"""

TOOLTIP_SCRIPT = """
(function () {
  var tooltip = document.getElementById('chart-tooltip');
  function showTip(x, y, html) {
    tooltip.innerHTML = html;
    tooltip.style.left = x + 'px';
    tooltip.style.top = (y - 10) + 'px';
    tooltip.style.opacity = '1';
  }
  function hideTip() { tooltip.style.opacity = '0'; }

  document.querySelectorAll('.chart-bar').forEach(function (bar) {
    function onEnter() {
      var rect = bar.getBoundingClientRect();
      showTip(rect.right, rect.top, '<strong>' + bar.dataset.value + '</strong> — ' + bar.dataset.label);
    }
    bar.addEventListener('mouseenter', onEnter);
    bar.addEventListener('focus', onEnter);
    bar.addEventListener('mouseleave', hideTip);
    bar.addEventListener('blur', hideTip);
  });

  document.querySelectorAll('.chart-wrap').forEach(function (wrap) {
    var svg = wrap.querySelector('svg');
    var crosshair = svg.querySelector('.chart-crosshair');
    svg.querySelectorAll('.chart-hit').forEach(function (hit) {
      hit.addEventListener('mouseenter', function () { crosshair.style.opacity = '1'; });
      hit.addEventListener('mouseleave', function () { crosshair.style.opacity = '0'; hideTip(); });
      hit.addEventListener('mousemove', function (e) {
        var x = hit.getAttribute('data-x');
        crosshair.setAttribute('x1', x);
        crosshair.setAttribute('x2', x);
        var rows = ['<strong>' + hit.dataset.cat + '</strong>'];
        for (var key in hit.dataset) {
          if (/^s\\d+$/.test(key)) rows.push(hit.dataset[key]);
        }
        showTip(e.clientX, e.clientY, rows.join('<br>'));
      });
    });
  });
})();
"""


def _html_table(df) -> str:
    if df.empty:
        return "<p><em>No data yet.</em></p>"
    return df.to_html(index=False, float_format="{:,.2f}".format)


def _revenue_trend_chart(df) -> str:
    if df.empty:
        return '<p class="chart-empty">No data yet.</p>'
    categories = [d.strftime("%Y-%m") for d in df["month"]]
    series = [
        ("Revenue", CATEGORICAL[0], df["revenue"].fillna(0).tolist()),
        ("Profit", CATEGORICAL[1], df["profit"].fillna(0).tolist()),
    ]
    return line_chart(categories, series)


def _top_products_chart(df) -> str:
    # The sample catalog reuses names across product variants (different SKU,
    # same display name), so the product_id disambiguates identically-named bars.
    labels = df["product_name"] + " (" + df["product_id"] + ")"
    items = list(zip(labels, df["total_revenue"].fillna(0)))
    return bar_chart(items, CATEGORICAL[0])


def _top_customers_chart(df) -> str:
    names = df["first_name"].fillna("") + " " + df["last_name"].fillna("")
    items = list(zip(names, df["total_spent"].fillna(0)))
    return bar_chart(items, CATEGORICAL[1])


def _channel_chart(df) -> str:
    if df.empty:
        return '<p class="chart-empty">No data yet.</p>'
    by_channel = (
        df.groupby("channel")["total_revenue"].sum().sort_values(ascending=False)
    )
    items = list(by_channel.items())
    colors = CATEGORICAL[: len(items)]
    return bar_chart(items, colors)


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

    charts = {
        "monthly_revenue_trend": _revenue_trend_chart(reports["monthly_revenue_trend"]),
        "top_products_by_revenue": _top_products_chart(reports["top_products_by_revenue"]),
        "top_customers_by_ltv": _top_customers_chart(reports["top_customers_by_ltv"]),
        "channel_payment_performance": _channel_chart(reports["channel_payment_performance"]),
    }

    total_revenue = reports["monthly_revenue_trend"]["revenue"].fillna(0).sum()
    total_profit = reports["monthly_revenue_trend"]["profit"].fillna(0).sum()

    html = [
        "<html><head><meta charset='utf-8'>",
        "<title>Retail Analytics - Business Report</title>",
        f"<style>{PAGE_STYLE}</style>",
        "</head><body>",
        "<h1>Retail Analytics - Business Report</h1>",
        f'<p class="subtitle">Total revenue {fmt_money(total_revenue)} &middot; '
        f'total profit {fmt_money(total_profit)}, across the loaded history.</p>',
    ]

    for name in ("monthly_revenue_trend", "top_products_by_revenue",
                 "top_customers_by_ltv", "channel_payment_performance"):
        html.append(f'<div class="report"><h2>{REPORT_TITLES[name]}</h2>{charts[name]}')
        html.append(_html_table(reports[name]))
        html.append("</div>")

    html.append(f'<div class="report"><h2>{REPORT_TITLES["data_quality_summary"]}</h2>')
    html.append(_html_table(reports["data_quality_summary"]))
    html.append("</div>")

    html.append('<div id="chart-tooltip" class="chart-tooltip"></div>')
    html.append(f"<script>{TOOLTIP_SCRIPT}</script>")
    html.append("</body></html>")

    html_path = OUTPUT_DIR / "business_report.html"
    html_path.write_text("\n".join(html), encoding="utf-8")
    log.info("[reports] HTML summary (with charts) -> %s", html_path)


if __name__ == "__main__":
    main()

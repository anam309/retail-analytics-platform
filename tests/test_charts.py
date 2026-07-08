from reports.charts import bar_chart, fmt_money, line_chart


def test_fmt_money_scales():
    assert fmt_money(950) == "$950"
    assert fmt_money(12_345) == "$12.3K"
    assert fmt_money(4_200_000) == "$4.2M"


def test_bar_chart_renders_one_group_per_item():
    items = [("Widget", 100.0), ("Gadget", 50.0)]
    svg = bar_chart(items, "#2a78d6")

    assert svg.count('class="chart-bar"') == 2
    assert "Widget" in svg
    assert "$100" in svg


def test_bar_chart_empty_shows_placeholder():
    svg = bar_chart([], "#2a78d6")
    assert "No data yet" in svg
    assert "<svg" not in svg


def test_bar_chart_accepts_per_bar_colors():
    items = [("In-Store", 300.0), ("Online", 200.0)]
    svg = bar_chart(items, ["#2a78d6", "#1baf7a"])

    assert "fill:#2a78d6" in svg
    assert "fill:#1baf7a" in svg


def test_line_chart_has_one_hit_column_per_category_and_a_legend_per_series():
    categories = ["2024-01", "2024-02", "2024-03"]
    series = [
        ("Revenue", "#2a78d6", [100.0, 120.0, 90.0]),
        ("Profit", "#1baf7a", [40.0, 50.0, 35.0]),
    ]
    svg = line_chart(categories, series)

    assert svg.count('class="chart-hit"') == 3
    assert svg.count('class="legend-item"') == 2
    assert svg.count('class="chart-line"') == 2


def test_line_chart_empty_shows_placeholder():
    assert "No data yet" in line_chart([], [])

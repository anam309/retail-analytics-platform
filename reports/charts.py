"""
reports/charts.py — Minimal hand-rolled SVG chart generation for the business
report HTML. No charting library dependency: bars and lines are plain SVG
built directly from the report DataFrames.

Palette, mark specs, and interaction follow the project's dataviz guidelines:
fixed categorical hue order, a single hue per magnitude ranking, 2px lines,
rounded bar ends (square at the baseline), hairline gridlines, and a shared
hover tooltip (see the <script>/<style> block generate.py embeds once).
"""

from __future__ import annotations

from html import escape

# ── Palette — fixed categorical order; sequential contexts take slots in turn ─
CATEGORICAL = ["#2a78d6", "#1baf7a", "#eda100", "#4a3aa7"]  # blue, aqua, yellow, violet
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
BASELINE = "#c3c2b7"


def _esc(value) -> str:
    return escape(str(value), quote=True)


def _truncate(label: str, max_len: int) -> str:
    return label if len(label) <= max_len else label[: max_len - 1] + "…"


def fmt_money(v: float) -> str:
    v = float(v or 0)
    if abs(v) >= 1_000_000:
        return f"${v / 1_000_000:.1f}M"
    if abs(v) >= 1_000:
        return f"${v / 1_000:.1f}K"
    return f"${v:,.0f}"


def _nice_ceiling(value: float) -> float:
    """Round up to a clean axis maximum (1/2/5 * 10^n)."""
    if value <= 0:
        return 1.0
    import math
    exp = math.floor(math.log10(value))
    base = value / (10 ** exp)
    step = 1 if base <= 1 else 2 if base <= 2 else 5 if base <= 5 else 10
    return step * (10 ** exp)


def bar_chart(items: list[tuple[str, float]], color: str | list[str], *, width: int = 640,
              bar_h: int = 22, gap: int = 10, value_fmt=fmt_money) -> str:
    """
    Horizontal bar chart. `items` is [(label, value), ...], already sorted.

    `color` is either one hex string — a single-hue magnitude ranking (top
    products, top customers) — or a list of hex strings, one per bar, for a
    small set of distinct categories (e.g. channels) where each bar is its
    own identity rather than a rank of the same kind of entity.
    """
    if not items:
        return '<p class="chart-empty">No data yet.</p>'

    colors = [color] * len(items) if isinstance(color, str) else color
    n = len(items)
    max_val = max((v for _, v in items), default=1) or 1
    label_col = 190
    right_pad = 90
    plot_w = width - label_col - right_pad
    height = n * (bar_h + gap) + gap

    rows = []
    for i, (label, value) in enumerate(items):
        y = gap + i * (bar_h + gap)
        w = max(2.0, (value / max_val) * plot_w)
        r = min(4.0, w / 2, bar_h / 2)
        x0 = label_col
        bar_color = colors[i]
        # Rounded right end, square left (baseline) end.
        path = (
            f"M {x0},{y} H {x0 + w - r:.1f} "
            f"A {r:.1f},{r:.1f} 0 0 1 {x0 + w:.1f},{y + r:.1f} "
            f"V {y + bar_h - r:.1f} "
            f"A {r:.1f},{r:.1f} 0 0 1 {x0 + w - r:.1f},{y + bar_h} "
            f"H {x0} Z"
        )
        rows.append(f'''
        <g class="chart-bar" tabindex="0"
           data-label="{_esc(label)}" data-value="{_esc(value_fmt(value))}">
          <text x="{x0 - 10}" y="{y + bar_h / 2 + 4:.1f}" text-anchor="end" class="chart-label">{_esc(_truncate(label, 24))}</text>
          <path d="{path}" style="fill:{bar_color}"/>
          <text x="{x0 + w + 8:.1f}" y="{y + bar_h / 2 + 4:.1f}" class="chart-value">{_esc(value_fmt(value))}</text>
        </g>''')

    baseline = f'<line x1="{label_col}" y1="{gap / 2}" x2="{label_col}" y2="{height - gap / 2}" class="chart-baseline"/>'

    return f'''
    <svg class="chart" viewBox="0 0 {width} {height}" width="100%" height="{height}"
         preserveAspectRatio="xMinYMin meet" role="img" aria-label="Bar chart">
      {baseline}
      {"".join(rows)}
    </svg>'''


def line_chart(categories: list[str], series: list[tuple[str, str, list[float]]], *,
                width: int = 640, height: int = 280, value_fmt=fmt_money) -> str:
    """
    Multi-series line chart (e.g. monthly revenue vs. profit).

    categories: x-axis labels (e.g. ['2024-01', '2024-02', ...])
    series: [(name, color, values), ...] — values aligned with categories.
    """
    n = len(categories)
    if n == 0:
        return '<p class="chart-empty">No data yet.</p>'

    pad_l, pad_r, pad_t, pad_b = 56, 20, 16, 28
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    all_vals = [v for _, _, vals in series for v in vals]
    nice_max = _nice_ceiling(max(all_vals) if all_vals else 1)

    def x_at(i: int) -> float:
        return pad_l + (i / max(1, n - 1)) * plot_w

    def y_at(v: float) -> float:
        return pad_t + plot_h - (v / nice_max) * plot_h

    # Gridlines + y-axis ticks (4 steps)
    grid, ticks = [], []
    for s in range(5):
        val = nice_max * s / 4
        y = y_at(val)
        grid.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width - pad_r}" y2="{y:.1f}" class="chart-grid"/>')
        ticks.append(f'<text x="{pad_l - 8}" y="{y + 4:.1f}" text-anchor="end" class="chart-tick">{value_fmt(val)}</text>')

    # X-axis ticks, sparse
    every = max(1, n // 6)
    x_ticks = [
        f'<text x="{x_at(i):.1f}" y="{height - 8}" text-anchor="middle" class="chart-tick">{_esc(c)}</text>'
        for i, c in enumerate(categories) if i % every == 0 or i == n - 1
    ]

    lines, legend, end_labels = [], [], []
    for name, color, vals in series:
        points = " ".join(f"{x_at(i):.1f},{y_at(v):.1f}" for i, v in enumerate(vals))
        lines.append(f'<polyline points="{points}" class="chart-line" style="stroke:{color}"/>')
        if vals:
            ex, ey = x_at(n - 1), y_at(vals[-1])
            lines.append(f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="4" style="fill:{color}"/>')
            # Text stays in a neutral ink token even though the mark is colored —
            # the colored endpoint dot beside it carries the series identity.
            end_labels.append(
                f'<text x="{min(ex + 8, width - pad_r - 4):.1f}" y="{ey + 4:.1f}" '
                f'class="chart-endlabel">{_esc(name)}</text>'
            )
        legend.append(
            f'<span class="legend-item"><span class="legend-swatch" style="background:{color}"></span>{_esc(name)}</span>'
        )

    # Invisible full-height hit columns, one per category, for hover + crosshair.
    col_w = plot_w / max(1, n - 1) if n > 1 else plot_w
    hits = []
    for i, cat in enumerate(categories):
        attrs = " ".join(f'data-s{j}="{_esc(name)}: {_esc(value_fmt(vals[i]))}"' for j, (name, _, vals) in enumerate(series))
        hits.append(
            f'<rect x="{x_at(i) - col_w / 2:.1f}" y="{pad_t}" width="{col_w:.1f}" height="{plot_h}" '
            f'class="chart-hit" data-x="{x_at(i):.1f}" data-cat="{_esc(cat)}" {attrs}/>'
        )

    return f'''
    <div class="chart-wrap">
      <div class="chart-legend">{"".join(legend)}</div>
      <svg class="chart" viewBox="0 0 {width} {height}" width="100%" height="{height}"
           preserveAspectRatio="xMinYMin meet" role="img" aria-label="Line chart">
        {"".join(grid)}
        <line x1="{pad_l}" y1="{y_at(0):.1f}" x2="{width - pad_r}" y2="{y_at(0):.1f}" class="chart-baseline"/>
        {"".join(ticks)}
        {"".join(x_ticks)}
        {"".join(lines)}
        {"".join(end_labels)}
        <line class="chart-crosshair" x1="0" y1="{pad_t}" x2="0" y2="{pad_t + plot_h}"/>
        {"".join(hits)}
      </svg>
    </div>'''

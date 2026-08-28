"""Inline SVG trend charts for the parent dashboard.

No JavaScript charting library and no matplotlib process: these are strings.
Colours come from CSS custom properties so the charts follow the page theme.
"""
from typing import Any, Optional, Sequence

W, H = 460, 210
PAD_L, PAD_R, PAD_T, PAD_B = 38, 12, 16, 26


def _nice_bounds(
    values: Sequence[float],
    band: Optional[tuple[float, float]],
    domain: Optional[tuple[float, float]] = None,
) -> tuple[float, float]:
    if domain:
        return domain
    pool = [v for v in values if v is not None]
    if band:
        pool = [*pool, band[0], band[1]]
    if not pool:
        return 0.0, 1.0
    lo, hi = min(pool), max(pool)
    if hi - lo < 1e-9:
        lo, hi = lo - 1, hi + 1
    pad = (hi - lo) * 0.15
    return max(0.0, lo - pad), hi + pad


def _fmt(value: float) -> str:
    return f"{value:.0f}" if abs(value) >= 10 else f"{value:.1f}"


def line_chart(
    title: str,
    values: Sequence[Optional[float]],
    labels: Sequence[str],
    band: Optional[tuple[float, float]] = None,
    band_label: str = "",
    unit: str = "",
    domain: Optional[tuple[float, float]] = None,
) -> str:
    """One metric over time. `band` shades the healthy range, e.g. 100-150 wpm."""
    points = [(i, v) for i, v in enumerate(values) if v is not None]
    if not points:
        return (
            f'<figure class="chart chart--empty"><figcaption>{title}</figcaption>'
            f'<p class="chart-empty">Not enough sessions yet.</p></figure>'
        )

    lo, hi = _nice_bounds([v for _, v in points], band, domain)
    span_x = max(len(values) - 1, 1)
    plot_w = W - PAD_L - PAD_R
    plot_h = H - PAD_T - PAD_B

    def x(i: int) -> float:
        return PAD_L + (i / span_x) * plot_w

    def y(v: float) -> float:
        return PAD_T + (1 - (v - lo) / (hi - lo)) * plot_h

    parts: list[str] = [
        f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{title} over time" class="chart-svg">'
    ]

    for frac in (0.0, 0.5, 1.0):
        gy = PAD_T + frac * plot_h
        val = hi - frac * (hi - lo)
        parts.append(f'<line x1="{PAD_L}" y1="{gy:.1f}" x2="{W - PAD_R}" y2="{gy:.1f}" class="chart-grid"/>')
        parts.append(f'<text x="{PAD_L - 8}" y="{gy + 4:.1f}" class="chart-tick" text-anchor="end">{_fmt(val)}</text>')

    path = " ".join(
        f"{'M' if n == 0 else 'L'}{x(i):.1f},{y(v):.1f}" for n, (i, v) in enumerate(points)
    )
    area = (
        f"{path} L{x(points[-1][0]):.1f},{PAD_T + plot_h:.1f} "
        f"L{x(points[0][0]):.1f},{PAD_T + plot_h:.1f} Z"
    )
    parts.append(f'<path d="{area}" class="chart-area"/>')

    if band:
        top, bottom = y(band[1]), y(band[0])
        parts.append(
            f'<rect x="{PAD_L}" y="{top:.1f}" width="{plot_w}" height="{max(bottom - top, 1):.1f}" '
            f'class="chart-band"/>'
        )
        if band_label:
            parts.append(
                f'<text x="{PAD_L + 6}" y="{top - 5:.1f}" class="chart-band-label">{band_label}</text>'
            )

    parts.append(f'<path d="{path}" class="chart-line"/>')

    for i, v in points:
        parts.append(
            f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="4" class="chart-dot">'
            f'<title>{labels[i] if i < len(labels) else ""}: {_fmt(v)}{unit}</title></circle>'
        )

    if labels:
        parts.append(
            f'<text x="{PAD_L}" y="{H - 8}" class="chart-tick">{labels[points[0][0]]}</text>'
        )
        if len(points) > 1:
            parts.append(
                f'<text x="{W - PAD_R}" y="{H - 8}" class="chart-tick" text-anchor="end">'
                f'{labels[points[-1][0]]}</text>'
            )

    parts.append("</svg>")

    latest = points[-1][1]
    return (
        f'<figure class="chart">'
        f'<figcaption><span class="chart-title">{title}</span>'
        f'<span class="chart-latest">{_fmt(latest)}{unit}</span></figcaption>'
        f'{"".join(parts)}</figure>'
    )


def bars(title: str, rows: list[tuple[str, float, float]]) -> str:
    """Horizontal bars for the seven idea dimensions. rows: (label, value, max)."""
    if not rows:
        return ""
    out = [f'<figure class="chart chart--bars"><figcaption><span class="chart-title">{title}</span></figcaption><ul class="barlist">']
    for label, value, maximum in rows:
        pct = 0.0 if maximum <= 0 else max(0.0, min(1.0, value / maximum)) * 100
        out.append(
            f'<li><span class="bar-label">{label}</span>'
            f'<span class="bar-track"><span class="bar-fill" style="width:{pct:.0f}%"></span></span>'
            f'<span class="bar-value">{value:.1f}</span></li>'
        )
    out.append("</ul></figure>")
    return "".join(out)


# --- single-session report -------------------------------------------------

MAP_W, MAP_H = 640, 190


def speech_map(
    envelope: Sequence[float],
    pauses: Sequence[dict],
    fillers: Sequence[dict],
    duration: float,
    opening_window: float = 15.0,
) -> str:
    """One speech laid out on a time axis.

    Shows the loudness curve, where every long pause fell, and where each filler
    landed. Averages hide the thing a parent most wants to see: whether the
    hesitations were bunched at the start, and whether the voice faded at the end.
    """
    if not envelope or duration <= 0:
        return ('<figure class="chart chart--empty"><figcaption>Speech map</figcaption>'
                '<p class="chart-empty">No audio analysis for this session.</p></figure>')

    pad_l, pad_r, pad_t, pad_b = 34, 14, 16, 34
    plot_w = MAP_W - pad_l - pad_r
    plot_h = MAP_H - pad_t - pad_b
    floor = pad_t + plot_h

    def tx(seconds: float) -> float:
        return pad_l + max(0.0, min(1.0, seconds / duration)) * plot_w

    parts = [f'<svg viewBox="0 0 {MAP_W} {MAP_H}" role="img" '
             f'aria-label="Loudness, pauses and fillers over the speech" class="chart-svg">']

    # the opening 15 seconds, where a cluster of pauses means a weak start
    if duration > opening_window:
        parts.append(
            f'<rect x="{pad_l}" y="{pad_t}" width="{tx(opening_window) - pad_l:.1f}" '
            f'height="{plot_h}" class="map-opening"/>'
        )
        parts.append(f'<text x="{tx(opening_window) + 5:.1f}" y="{pad_t + 11}" '
                     f'class="map-note">first 15s</text>')

    for pause in pauses:
        start = tx(float(pause.get("at", 0)))
        width = max(tx(float(pause.get("at", 0)) + float(pause.get("length", 0))) - start, 2.0)
        parts.append(f'<rect x="{start:.1f}" y="{pad_t}" width="{width:.1f}" '
                     f'height="{plot_h}" class="map-pause"><title>'
                     f'{pause.get("length")}s pause at {pause.get("at")}s</title></rect>')

    step = plot_w / max(len(envelope) - 1, 1)
    pts = [(pad_l + i * step, floor - v * plot_h) for i, v in enumerate(envelope)]
    line = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(pts))
    parts.append(f'<path d="{line} L{pts[-1][0]:.1f},{floor} L{pad_l},{floor} Z" class="map-area"/>')
    parts.append(f'<path d="{line}" class="map-line"/>')

    for filler in fillers:
        x = tx(float(filler.get("at", 0)))
        parts.append(f'<circle cx="{x:.1f}" cy="{floor + 11}" r="4" class="map-filler">'
                     f'<title>"{filler.get("word")}" at {filler.get("at")}s</title></circle>')

    parts.append(f'<line x1="{pad_l}" y1="{floor}" x2="{MAP_W - pad_r}" y2="{floor}" class="chart-grid"/>')
    parts.append(f'<text x="{pad_l}" y="{MAP_H - 6}" class="chart-tick">0s</text>')
    parts.append(f'<text x="{MAP_W - pad_r}" y="{MAP_H - 6}" class="chart-tick" '
                 f'text-anchor="end">{duration:.0f}s</text>')
    parts.append(f'<text x="{pad_l - 8}" y="{pad_t + 10}" class="chart-tick" text-anchor="end">loud</text>')
    parts.append(f'<text x="{pad_l - 8}" y="{floor}" class="chart-tick" text-anchor="end">quiet</text>')
    parts.append("</svg>")

    legend = (
        '<div class="legend">'
        '<span><i class="swatch swatch--line"></i>loudness</span>'
        '<span><i class="swatch swatch--pause"></i>pause over 0.7s</span>'
        '<span><i class="swatch swatch--filler"></i>filler word</span>'
        "</div>"
    )
    return ('<figure class="chart"><figcaption><span class="chart-title">Speech map</span>'
            f'</figcaption>{"".join(parts)}{legend}</figure>')


def segment_bars(title: str, segments: list[tuple[str, float]],
                 band: Optional[tuple[float, float]] = None, unit: str = "") -> str:
    """Vertical bars, one per time slice. Used for pace across the speech."""
    if not segments:
        return ""

    values = [v for _, v in segments]
    hi = max([*values, band[1] if band else 0]) * 1.15 or 1.0
    w, h = 640, 180
    pad_l, pad_b, pad_t = 34, 30, 12
    plot_w, plot_h = w - pad_l - 14, h - pad_t - pad_b
    slot = plot_w / len(segments)
    bar_w = min(slot * 0.62, 46)

    parts = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{title}" class="chart-svg">']

    if band:
        top = pad_t + (1 - band[1] / hi) * plot_h
        bottom = pad_t + (1 - band[0] / hi) * plot_h
        parts.append(f'<rect x="{pad_l}" y="{top:.1f}" width="{plot_w}" '
                     f'height="{max(bottom - top, 1):.1f}" class="chart-band"/>')

    for i, (label, value) in enumerate(segments):
        bar_h = max((value / hi) * plot_h, 2)
        x = pad_l + i * slot + (slot - bar_w) / 2
        y = pad_t + plot_h - bar_h
        cls = "map-bar"
        if band and value > band[1]:
            cls += " map-bar--high"
        elif band and value < band[0]:
            cls += " map-bar--low"
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" '
                     f'rx="4" class="{cls}"><title>{label}: {value:.0f}{unit}</title></rect>')
        parts.append(f'<text x="{x + bar_w / 2:.1f}" y="{h - 10}" class="chart-tick" '
                     f'text-anchor="middle">{label}</text>')

    parts.append(f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{w - 14}" y2="{pad_t + plot_h}" class="chart-grid"/>')
    parts.append("</svg>")
    return (f'<figure class="chart"><figcaption><span class="chart-title">{title}</span>'
            f'</figcaption>{"".join(parts)}</figure>')


def calendar(days: dict[str, int], weeks: int = 14) -> str:
    """A practice heatmap, most recent week last.

    Rhythm is the thing a parent can actually influence, and a grid shows it
    faster than any streak number can.
    """
    from datetime import date, timedelta

    today = date.today()
    # Start on the Monday of the earliest week shown.
    start = today - timedelta(days=today.weekday() + 7 * (weeks - 1))
    peak = max(days.values()) if days else 0

    cell, gap = 13, 3
    pad_l, pad_t = 28, 16
    w = pad_l + weeks * (cell + gap)
    h = pad_t + 7 * (cell + gap) + 16

    parts = [f'<svg viewBox="0 0 {w} {h}" class="cal" role="img" '
             f'aria-label="Practice over the last {weeks} weeks">']

    for i, label in ((0, "Mon"), (2, "Wed"), (4, "Fri")):
        y = pad_t + i * (cell + gap) + cell - 3
        parts.append(f'<text x="0" y="{y}" class="cal-label">{label}</text>')

    last_month = None
    last_label = -99
    for week in range(weeks):
        for weekday in range(7):
            day = start + timedelta(days=week * 7 + weekday)
            if day > today:
                continue
            count = days.get(day.isoformat(), 0)
            level = 0 if count == 0 else (1 + min(int(count / max(peak, 1) * 3), 2))
            x = pad_l + week * (cell + gap)
            y = pad_t + weekday * (cell + gap)
            parts.append(
                f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="3" '
                f'class="cal-cell cal-cell--{level}">'
                f'<title>{day.isoformat()}: {count} speech{"es" if count != 1 else ""}</title></rect>'
            )
        month = (start + timedelta(days=week * 7)).strftime("%b")
        if month != last_month and week - last_label >= 3:
            parts.append(f'<text x="{pad_l + week * (cell + gap)}" y="10" class="cal-label">{month}</text>')
            last_month, last_label = month, week

    parts.append("</svg>")
    return "".join(parts)

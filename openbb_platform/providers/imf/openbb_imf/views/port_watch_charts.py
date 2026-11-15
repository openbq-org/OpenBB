"""Plotly chart builders for IMF Port Watch endpoints."""

import json
import math
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openbb_charting.core.openbb_figure import OpenBBFigure


def _theme(theme: str = "dark") -> dict[str, Any]:
    """Return color tokens for the requested theme."""
    if theme == "dark":
        return {
            "plot_bgcolor": "rgba(21,21,21,1)",
            "paper_bgcolor": "rgba(21,21,21,1)",
            "font_color": "#ffffff",
            "annotation_color": "#aaaaaa",
            "geo_bgcolor": "rgba(0,0,0,0)",
            "landcolor": "#3a5d3a",
            "oceancolor": "#223355",
            "countrycolor": "#cccccc",
            "coastlinecolor": "#cccccc",
        }
    return {
        "plot_bgcolor": "rgba(255,255,255,1)",
        "paper_bgcolor": "rgba(255,255,255,1)",
        "font_color": "#000000",
        "annotation_color": "#555555",
        "geo_bgcolor": "rgba(255,255,255,0)",
        "landcolor": "#3a5d3a",
        "oceancolor": "#3a5d99",
        "countrycolor": "#cccccc",
        "coastlinecolor": "#cccccc",
    }


def _source_annotation(th: dict[str, Any]) -> dict[str, Any]:
    """Return the IMF Port Watch source-attribution annotation."""
    return dict(
        text=f"Source: IMF Port Watch — {datetime.now(UTC).date().isoformat()}",
        x=0.5,
        xref="paper",
        yref="paper",
        y=1,
        yshift=10,
        showarrow=False,
        font=dict(size=10, color=th["annotation_color"]),
        xanchor="center",
        yanchor="bottom",
        opacity=0.6,
    )


def figure_to_json(fig) -> dict[str, Any]:
    """Convert a Plotly figure to the JSON dict Workspace renders."""
    fig_dict = json.loads(fig.to_json())
    fig_dict["config"] = {"displayModeBar": False}
    return fig_dict


def clean_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Coerce NaN floats inside ``records`` to ``None`` for JSON serialization."""
    cleaned: list[dict[str, Any]] = []
    for row in records:
        out: dict[str, Any] = {}
        for k, v in row.items():
            if isinstance(v, float) and math.isnan(v):
                out[k] = None
            else:
                out[k] = v
        cleaned.append(out)
    return cleaned


def _empty_figure(message: str, theme: str = "dark"):
    """Return a blank figure carrying a centered ``message``."""
    import plotly.graph_objects as go

    th = _theme(theme)
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        showarrow=False,
        font=dict(color=th["font_color"], size=14),
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
    )
    fig.update_layout(
        paper_bgcolor=th["paper_bgcolor"],
        plot_bgcolor=th["plot_bgcolor"],
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        margin=dict(l=20, r=20, t=20, b=20),
    )
    return fig


_VESSEL_TYPES = (
    ("container", "Container", "#2E86AB"),
    ("dry_bulk", "Dry Bulk", "#A23B72"),
    ("general_cargo", "General Cargo", "#F18F01"),
    ("roro", "Ro-Ro", "#C73E1D"),
    ("tanker", "Tanker", "#3B6064"),
)

_LINE_PALETTE = (
    "#2E86AB",
    "#A23B72",
    "#F18F01",
    "#C73E1D",
    "#3B6064",
    "#7B5C5C",
    "#5A6F8A",
    "#F5C16C",
    "#6CA77F",
    "#A66DD4",
    "#D4915F",
    "#5C8A8A",
)

_PORT_METRIC_GROUPS = {
    "portcalls": ("portcalls", "Port Calls", "calls/day"),
    "import": ("import", "Imports (metric tons)", "tons/day"),
    "export": ("export", "Exports (metric tons)", "tons/day"),
}

_TRADENOW_LINE_METRICS = {
    "trade_value": (
        "Trade Value Index (2019 = 100)",
        [
            ("value_import_total", "Imports", "#2E86AB"),
            ("value_export_total", "Exports", "#F18F01"),
        ],
        "Index (2019 = 100)",
    ),
    "trade_volume": (
        "Trade Volume Index (2019 = 100)",
        [
            ("volume_import_total", "Imports", "#2E86AB"),
            ("volume_export_total", "Exports", "#F18F01"),
        ],
        "Index (2019 = 100)",
    ),
}

_TRADENOW_PORTCALLS = (
    "AIS Port Calls",
    [
        ("ais_portcalls_container", "Container", "#2E86AB"),
        ("ais_portcalls_dry_bulk", "Dry Bulk", "#A23B72"),
        ("ais_portcalls_general_cargo", "General Cargo", "#F18F01"),
        ("ais_portcalls_roro", "Ro-Ro", "#C73E1D"),
        ("ais_portcalls_tanker", "Tanker", "#3B6064"),
    ],
    "calls/month",
)

_ALERT_COLORS: dict[str | None, str] = {
    "RED": "#d62728",
    "ORANGE": "#ff7f0e",
    "GREEN": "#2ca02c",
    None: "#7f7f7f",
}


def build_activity_chart(
    rows: list[dict[str, Any]],
    title: str,
    metric: str = "portcalls",
    *,
    theme: str = "dark",
):
    """Stacked-area daily activity chart with a 30-day moving average overlay."""
    import plotly.graph_objects as go
    from pandas import DataFrame, to_datetime

    groups = _PORT_METRIC_GROUPS
    if metric not in groups:
        metric = next(iter(groups))
    base, metric_label, y_unit = groups[metric]

    if not rows:
        return _empty_figure("No activity data for the selected window.", theme)

    df = DataFrame(rows)
    if "date" not in df.columns:
        return _empty_figure("Activity rows are missing a 'date' field.", theme)
    df["date"] = to_datetime(df["date"])
    df = df.sort_values("date")

    th = _theme(theme)
    fig = go.Figure()

    has_any = False
    for suffix, label, color in _VESSEL_TYPES:
        col = f"{base}_{suffix}"
        if col not in df.columns:
            continue
        has_any = True
        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df[col].fillna(0),
                mode="lines",
                name=label,
                stackgroup="vessels",
                line=dict(width=0.5, color=color),
                hovertemplate=(
                    f"<b>{label}</b><br>%{{x|%Y-%m-%d}}: %{{y:,.0f}}<extra></extra>"
                ),
            )
        )

    if not has_any:
        return _empty_figure(
            f"No '{metric}' breakdown columns present in this dataset.", theme
        )

    total_col = next((c for c in (base, f"{base}_total") if c in df.columns), None)
    if total_col:
        rolling = df[total_col].astype(float).rolling(window=30, min_periods=5).mean()
        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=rolling,
                mode="lines",
                name=f"30-day MA ({total_col})",
                line=dict(color=th["font_color"], width=2, dash="dot"),
                hovertemplate=(
                    "<b>30-day MA</b><br>%{x|%Y-%m-%d}: %{y:,.0f}<extra></extra>"
                ),
            )
        )

    fig.update_layout(
        title=dict(
            text=f"{title} — Daily {metric_label}",
            font=dict(size=16, color=th["font_color"]),
            x=0.5,
        ),
        paper_bgcolor=th["paper_bgcolor"],
        plot_bgcolor=th["plot_bgcolor"],
        font=dict(color=th["font_color"]),
        xaxis=dict(showgrid=False, color=th["font_color"]),
        yaxis=dict(
            title=y_unit,
            showgrid=True,
            gridcolor="rgba(128,128,128,0.2)",
            color=th["font_color"],
        ),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="top", y=-0.12, xanchor="center", x=0.5),
        margin=dict(l=60, r=20, t=60, b=70),
        annotations=[_source_annotation(th)],
    )
    return fig


def build_monthly_trade_chart(
    rows: list[dict[str, Any]],
    region_name: str,
    metric: str = "trade_value",
    theme: str = "dark",
):
    """Line / stacked-area chart for monthly TradeNow indices."""
    import plotly.graph_objects as go
    from pandas import DataFrame, to_datetime

    if not rows:
        return _empty_figure("No monthly trade data for the selected region.", theme)
    df = DataFrame(rows)
    if "date" not in df.columns:
        return _empty_figure("Monthly trade rows missing a 'date' field.", theme)
    df["date"] = to_datetime(df["date"])
    df = df.sort_values("date")

    th = _theme(theme)
    fig = go.Figure()

    if metric == "portcalls":
        title_metric, traces, y_unit = _TRADENOW_PORTCALLS
        for col, label, color in traces:
            if col not in df.columns:
                continue
            fig.add_trace(
                go.Scatter(
                    x=df["date"],
                    y=df[col].fillna(0),
                    mode="lines",
                    name=label,
                    stackgroup="vessels",
                    line=dict(width=0.5, color=color),
                    hovertemplate=(
                        f"<b>{label}</b><br>%{{x|%Y-%m}}: %{{y:,.0f}}<extra></extra>"
                    ),
                )
            )
    else:
        if metric not in _TRADENOW_LINE_METRICS:
            metric = "trade_value"
        title_metric, traces, y_unit = _TRADENOW_LINE_METRICS[metric]
        for col, label, color in traces:
            if col not in df.columns:
                continue
            fig.add_trace(
                go.Scatter(
                    x=df["date"],
                    y=df[col],
                    mode="lines+markers",
                    name=label,
                    line=dict(width=2, color=color),
                    marker=dict(size=4),
                    hovertemplate=(
                        f"<b>{label}</b><br>%{{x|%Y-%m}}: %{{y:,.2f}}<extra></extra>"
                    ),
                )
            )

    if not fig.data:
        return _empty_figure(f"No '{metric}' columns present in this dataset.", theme)

    fig.update_layout(
        title=dict(
            text=f"{region_name} — Monthly {title_metric}",
            font=dict(size=16, color=th["font_color"]),
            x=0.5,
        ),
        paper_bgcolor=th["paper_bgcolor"],
        plot_bgcolor=th["plot_bgcolor"],
        font=dict(color=th["font_color"]),
        xaxis=dict(showgrid=False, color=th["font_color"]),
        yaxis=dict(
            title=y_unit,
            showgrid=True,
            gridcolor="rgba(128,128,128,0.2)",
            color=th["font_color"],
        ),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="top", y=-0.12, xanchor="center", x=0.5),
        margin=dict(l=70, r=20, t=60, b=70),
    )
    return fig


def build_container_metric_chart(
    series: dict[str, list[dict[str, Any]]],
    port_name_map: dict[str, str],
    metric_label: str,
    theme: str = "dark",
):
    """Multi-series line+marker chart, one trace per port."""
    import plotly.graph_objects as go
    from pandas import DataFrame, to_datetime

    if not series or not any(series.values()):
        return _empty_figure("No container metric data for the selection.", theme)

    th = _theme(theme)
    fig = go.Figure()
    for i, (pid, rows) in enumerate(series.items()):
        if not rows:
            continue
        df = DataFrame(rows).sort_values("date")
        label = port_name_map.get(pid, pid)
        fig.add_trace(
            go.Scatter(
                x=to_datetime(df["date"]),
                y=df["value"],
                mode="lines+markers",
                name=label,
                line=dict(width=2, color=_LINE_PALETTE[i % len(_LINE_PALETTE)]),
                marker=dict(size=4),
                hovertemplate=(
                    f"<b>{label}</b><br>%{{x|%Y-%m}}: %{{y:,.0f}}<extra></extra>"
                ),
            )
        )

    if not fig.data:  # pragma: no cover -- unreachable: early return above guards `any(series.values())`
        return _empty_figure("No data for the selected ports.", theme)

    fig.update_layout(
        title=dict(
            text=f"Container Metrics — {metric_label}",
            font=dict(size=16, color=th["font_color"]),
            x=0.5,
        ),
        paper_bgcolor=th["paper_bgcolor"],
        plot_bgcolor=th["plot_bgcolor"],
        font=dict(color=th["font_color"]),
        xaxis=dict(showgrid=False, color=th["font_color"]),
        yaxis=dict(
            showgrid=True,
            gridcolor="rgba(128,128,128,0.2)",
            color=th["font_color"],
        ),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="top", y=-0.12, xanchor="center", x=0.5),
        margin=dict(l=70, r=20, t=60, b=70),
    )
    return fig


def build_disruption_sankey(
    rows: list[dict[str, Any]],
    event_label: str,
    theme: str = "dark",
):
    """Sankey of capacity spillover edges for a disruption event."""
    import plotly.graph_objects as go

    if not rows:
        return _empty_figure("No spillover data for the selected event.", theme)

    nodes: dict[int, str] = {}
    sources: list[int] = []
    targets: list[int] = []
    values: list[float] = []
    for r in rows:
        try:
            s = int(r["source"])
            t = int(r["target"])
            v = float(r["perc_disaster_capacity"])
        except (KeyError, TypeError, ValueError):
            continue
        nodes.setdefault(s, str(r.get("from_") or r.get("from_id") or f"node{s}"))
        nodes.setdefault(t, str(r.get("to_") or r.get("to_id") or f"node{t}"))
        sources.append(s)
        targets.append(t)
        values.append(v)

    if not values:
        return _empty_figure("No usable sankey edges for this event.", theme)

    max_idx = max(nodes) + 1
    labels = [nodes.get(i, f"node{i}") for i in range(max_idx)]

    th = _theme(theme)
    fig = go.Figure(
        go.Sankey(
            arrangement="snap",
            node=dict(
                label=labels,
                pad=14,
                thickness=14,
                line=dict(color=th["font_color"], width=0.4),
                color="#3B6064" if theme == "dark" else "#2E86AB",
            ),
            link=dict(
                source=sources,
                target=targets,
                value=values,
                color=(
                    "rgba(252,210,201,0.45)"
                    if theme == "dark"
                    else "rgba(46,134,171,0.35)"
                ),
                hovertemplate=(
                    "%{source.label} → %{target.label}: %{value:.2f}%<extra></extra>"
                ),
            ),
        )
    )
    fig.update_layout(
        title=dict(
            text=f"Capacity Spillover — {event_label}",
            font=dict(size=16, color=th["font_color"]),
            x=0.5,
        ),
        paper_bgcolor=th["paper_bgcolor"],
        plot_bgcolor=th["plot_bgcolor"],
        font=dict(color=th["font_color"]),
        margin=dict(l=20, r=20, t=60, b=20),
    )
    return fig


def _disruption_hover_html(row) -> str:
    """Render the HTML hover card for a disruption marker."""
    parts: list[str] = []
    name = row.get("eventname") or row.get("htmlname") or "Disruption Event"
    parts.append(f"<b>{name}</b><br>")
    et = row.get("eventtype")
    al = row.get("alertlevel")
    if et:
        parts.append(f"Type: {et}<br>")
    if al:
        parts.append(f"Alert: {al}<br>")
    fd, td = row.get("fromdate"), row.get("todate")
    if fd:
        parts.append(f"From: {fd}<br>")
    if td:
        parts.append(f"To: {td}<br>")
    n = row.get("n_affectedports")
    if n is not None and not (isinstance(n, float) and math.isnan(n)):
        parts.append(f"Affected ports: {int(n)}<br>")
    country = row.get("country")
    if country:
        parts.append(f"Country: {country}<br>")
    return "".join(parts)


def build_disruptions_map(
    disruptions: list[dict[str, Any]],
    theme: str = "dark",
):
    """Scattergeo of disruption events color-coded by alert level."""
    import plotly.graph_objects as go
    from pandas import DataFrame, Series

    if not disruptions:
        return _empty_figure("No disruptions match the selected filter.", theme)

    df = DataFrame(disruptions)
    if not {"lat", "long"}.issubset(df.columns):
        return _empty_figure("No georeferenced disruptions to display.", theme)
    df = df[df["lat"].notna() & df["long"].notna()]
    if df.empty:
        return _empty_figure("No georeferenced disruptions to display.", theme)

    th = _theme(theme)
    if "alertlevel" in df.columns:
        df["alertlevel_norm"] = df["alertlevel"].astype(str).str.upper()
        df["color"] = df["alertlevel_norm"].map(_ALERT_COLORS).fillna("#7f7f7f")
    else:
        df["alertlevel_norm"] = "UNKNOWN"
        df["color"] = "#d62728"

    df["hover"] = df.apply(_disruption_hover_html, axis=1)

    if "n_affectedports" in df.columns:
        sz = df["n_affectedports"].fillna(1).clip(lower=1).astype(float)
    else:
        sz = Series([1.0] * len(df))
    if sz.max() > 0:
        df["marker_size"] = 6 + 12 * (sz / sz.max())
    else:  # pragma: no cover -- unreachable: sz is clipped to >=1 or filled with 1.0
        df["marker_size"] = 7.0

    fig = go.Figure()
    for level in ("RED", "ORANGE", "GREEN"):
        sub = df[df["alertlevel_norm"] == level]
        if sub.empty:
            continue
        fig.add_trace(
            go.Scattergeo(
                lon=sub["long"],
                lat=sub["lat"],
                mode="markers",
                name=level.title(),
                marker=dict(
                    size=sub["marker_size"],
                    color=_ALERT_COLORS[level],
                    opacity=0.85,
                    line=dict(width=0.5, color="rgba(0,0,0,0.4)"),
                ),
                customdata=sub[["hover"]].values,
                hovertemplate="%{customdata[0]}<extra></extra>",
            )
        )

    other = df[~df["alertlevel_norm"].isin(("RED", "ORANGE", "GREEN"))]
    if not other.empty:
        fig.add_trace(
            go.Scattergeo(
                lon=other["long"],
                lat=other["lat"],
                mode="markers",
                name="Other",
                marker=dict(
                    size=other["marker_size"],
                    color="#7f7f7f",
                    opacity=0.7,
                ),
                customdata=other[["hover"]].values,
                hovertemplate="%{customdata[0]}<extra></extra>",
            )
        )

    fig.update_geos(
        projection_type="natural earth",
        showland=True,
        landcolor=th["landcolor"],
        showocean=True,
        oceancolor=th["oceancolor"],
        showcoastlines=True,
        coastlinecolor=th["coastlinecolor"],
        coastlinewidth=0.4,
        showcountries=True,
        countrycolor=th["countrycolor"],
        countrywidth=0.3,
        showframe=False,
        bgcolor=th["geo_bgcolor"],
        resolution=110,
    )
    fig.update_layout(
        autosize=True,
        height=600,
        margin={"r": 0, "t": 30, "l": 0, "b": 0},
        paper_bgcolor=th["paper_bgcolor"],
        plot_bgcolor=th["plot_bgcolor"],
        font=dict(color=th["font_color"]),
        annotations=[_source_annotation(th)],
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=-0.05,
            xanchor="center",
            x=0.5,
        ),
        dragmode="pan",
    )
    return fig


def _to_openbb_figure(fig) -> "OpenBBFigure":
    """Wrap a Plotly ``Figure`` in an ``OpenBBFigure``."""
    from openbb_charting.core.openbb_figure import OpenBBFigure

    return OpenBBFigure(fig)


def plot_country_activity(
    rows: list[dict[str, Any]],
    title: str,
    metric: str = "portcalls",
    theme: str = "dark",
) -> "OpenBBFigure":
    """Stacked-area daily activity chart for a country."""
    return _to_openbb_figure(build_activity_chart(rows, title, metric, theme=theme))


def plot_monthly_trade(
    rows: list[dict[str, Any]],
    region_name: str,
    metric: str = "trade_value",
    theme: str = "dark",
) -> "OpenBBFigure":
    """Monthly TradeNow chart wrapped as ``OpenBBFigure``."""
    return _to_openbb_figure(
        build_monthly_trade_chart(rows, region_name, metric, theme=theme)
    )


def plot_container_metrics(
    rows: list[dict[str, Any]],
    metric_label: str,
    theme: str = "dark",
    port_name_map: dict[str, str] | None = None,
) -> "OpenBBFigure":
    """Multi-series container metric chart wrapped as ``OpenBBFigure``."""
    series: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        pid = r.get("portid")
        if not pid:
            continue
        series.setdefault(pid, []).append(r)
    return _to_openbb_figure(
        build_container_metric_chart(
            series, port_name_map or {}, metric_label, theme=theme
        )
    )


def plot_disruption_sankey(
    rows: list[dict[str, Any]],
    event_label: str,
    theme: str = "dark",
) -> "OpenBBFigure":
    """Sankey spillover chart wrapped as ``OpenBBFigure``."""
    return _to_openbb_figure(build_disruption_sankey(rows, event_label, theme=theme))


def plot_disruptions_map(
    rows: list[dict[str, Any]],
    theme: str = "dark",
) -> "OpenBBFigure":
    """Disruption Scattergeo map wrapped as ``OpenBBFigure``."""
    return _to_openbb_figure(build_disruptions_map(rows, theme=theme))

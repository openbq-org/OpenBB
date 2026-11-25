"""Cboe options 3-D surface chart over DTE and strike."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from openbb_core.app.model.obbject import OBBject
    from openbb_core.provider.standard_models.options_chains import OptionsChainsData

SurfaceMetric = Literal[
    "implied_volatility", "delta", "gamma", "theta", "vega", "rho", "dex", "gex"
]

METRIC_TITLES = {
    "implied_volatility": "IV",
    "delta": "Delta",
    "gamma": "Gamma",
    "theta": "Theta",
    "vega": "Vega",
    "rho": "Rho",
    "dex": "DEX",
    "gex": "GEX",
}

OPTION_TYPE_LABELS = {"calls": "Call", "puts": "Put", "otm": "OTM", "itm": "ITM"}


def create_surface(
    data: OptionsChainsData,
    option_type: Literal["otm", "itm", "puts", "calls"] = "otm",
    metric: SurfaceMetric = "implied_volatility",
    dte_range: list[int] | None = None,
    moneyness: float | None = None,
    oi: bool = False,
    volume: bool = False,
    **kwargs,
) -> OBBject:
    """Chart an option metric as a 3-D surface over DTE and strike.

    Parameters
    ----------
    data : OptionsChainsData
        The loaded Cboe options chain.
    option_type : Literal["otm", "itm", "puts", "calls"]
        Which side of the chain to plot.
    metric : SurfaceMetric
        The Z-axis metric. Cboe publishes greeks alongside implied volatility.
    dte_range : list[int] | None
        Inclusive lower and upper days-to-expiry bounds.
    moneyness : float | None
        Restrict strikes to within this percent of the underlying price.
    oi : bool
        When True, drop contracts with no open interest.
    volume : bool
        When True, drop contracts that have not traded.

    Returns
    -------
    OBBject
        The plotted rows, with the Plotly figure attached to ``chart``.

    Raises
    ------
    OpenBBError
        If the requested metric is not present in the chain.
    """
    from openbb_core.app.model.abstract.error import OpenBBError
    from openbb_core.app.model.charts.chart import Chart
    from openbb_core.app.model.obbject import OBBject
    from openbb_core.app.utils import df_to_basemodel
    from pandas import concat

    from openbb_cboe import CHARTING_INSTALLED
    from openbb_cboe.utils.options.theme import CHART_CONFIG

    options = data.dataframe
    column_map = {c.lower(): c for c in options.columns}
    target = column_map.get(metric.lower(), metric)

    if target not in options.columns:
        raise OpenBBError(f"No {metric} data available in this chain.")

    last_price = float(data.underlying_price[0] or 0.0)
    symbol = data.underlying_symbol[0]
    calls = options.query(f"`option_type` == 'call' & `dte` >= 0 & `{target}` != 0")
    puts = options.query(f"`option_type` == 'put' & `dte` >= 0 & `{target}` != 0")

    if oi:
        calls = calls[calls["open_interest"] > 0]
        puts = puts[puts["open_interest"] > 0]

    if volume:
        calls = calls[calls["volume"] > 0]
        puts = puts[puts["volume"] > 0]

    def _between(frame, col, low, high):
        """Filter a frame to an inclusive range on one column."""
        return frame[(frame[col] >= low) & (frame[col] <= high)]

    if dte_range is not None and len(dte_range) > 1:
        calls = _between(calls, "dte", min(dte_range), max(dte_range))
        puts = _between(puts, "dte", min(dte_range), max(dte_range))

    if moneyness is not None and moneyness > 0:
        low = (1 - (moneyness / 100)) * last_price
        high = (1 + (moneyness / 100)) * last_price
        calls = _between(calls, "strike", low, high)
        puts = _between(puts, "strike", low, high)

    keys = ["expiration", "strike", "option_type"]

    if option_type == "otm":
        df = (
            concat(
                [
                    calls.query("`strike` > @last_price").set_index(keys),
                    puts.query("`strike` < @last_price").set_index(keys),
                ]
            )
            .sort_index()
            .reset_index()
        )
    elif option_type == "itm":
        df = (
            concat(
                [
                    calls.query("`strike` < @last_price").set_index(keys),
                    puts.query("`strike` > @last_price").set_index(keys),
                ]
            )
            .sort_index()
            .reset_index()
        )
    elif option_type == "calls":
        df = calls
    else:
        df = puts

    columns = [
        "expiration",
        "strike",
        "option_type",
        "dte",
        target,
        "open_interest",
        "volume",
    ]
    df = df[[c for c in dict.fromkeys(columns) if c in df.columns]].copy()
    metric_title = METRIC_TITLES.get(metric, metric.replace("_", " ").title())
    label = f"{symbol} {OPTION_TYPE_LABELS[option_type]} {metric_title} Surface"

    if oi:
        label += " With Open Interest"

    if volume:
        label += " Excluding Untraded Contracts"

    theme = kwargs.get("theme") or "dark"
    df.expiration = df.expiration.astype(str)
    output: Any = OBBject(results=df_to_basemodel(df))

    if not CHARTING_INSTALLED:
        return output

    from openbb_charting.charts.generic_charts import surface3d

    fig = surface3d(
        X=df["dte"],
        Y=df["strike"],
        Z=df[target],
        xtitle="DTE",
        ytitle="Strike",
        ztitle=metric_title,
        title=label,
        theme=theme,
    )
    text_color = "white" if theme == "dark" else "black"
    grid_color = "rgba(255,255,255,0.15)" if theme == "dark" else "rgba(0,0,0,0.15)"
    wall_color = "rgba(255,255,255,0.04)" if theme == "dark" else "rgba(0,0,0,0.04)"
    scene_axis = dict(
        color=text_color, gridcolor=grid_color, backgroundcolor=wall_color
    )
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=text_color),
        title=dict(font=dict(color=text_color)),
        scene=dict(xaxis=scene_axis, yaxis=scene_axis, zaxis=scene_axis),
        hoverlabel=dict(
            bgcolor="#0E0E0E" if theme == "dark" else "#FFFFFF",
            bordercolor=text_color,
            font=dict(color=text_color, size=12),
        ),
    )
    content = fig.show(config=CHART_CONFIG, external=True).to_plotly_json()
    output.chart = Chart(fig=fig, content=content, format="plotly")

    return output

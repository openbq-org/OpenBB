"""Cboe options term-structure chart across expirations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from openbb_core.app.model.obbject import OBBject
    from openbb_core.provider.standard_models.options_chains import OptionsChainsData


def create_term_structure(
    data: OptionsChainsData,
    strike: float | None = None,
    moneyness: float | None = None,
    metric: Literal["price", "iv"] = "iv",
    option_type: Literal["both", "calls", "puts"] = "both",
    **kwargs,
) -> OBBject:
    """Chart price or implied volatility at the nearest strike across expirations.

    Parameters
    ----------
    data : OptionsChainsData
        The loaded Cboe options chain.
    strike : float | None
        Target strike. Defaults to the nearest out-of-the-money strike per expiry.
    moneyness : float | None
        Select strikes this percent out-of-the-money instead of a fixed strike.
    metric : Literal["price", "iv"]
        Contract price or implied volatility.
    option_type : Literal["both", "calls", "puts"]
        Which side of the chain to plot.

    Returns
    -------
    OBBject
        The plotted rows, with the Plotly figure attached to ``chart``.

    Raises
    ------
    OpenBBError
        If implied volatility was requested but is absent from the chain.
    """
    from openbb_core.app.model.abstract.error import OpenBBError
    from openbb_core.app.model.obbject import OBBject
    from openbb_core.app.utils import df_to_basemodel
    from pandas import DataFrame, concat

    from openbb_cboe.utils.options.theme import finalize, new_figure

    if metric == "iv" and not data.has_iv:
        raise OpenBBError("No implied volatility data available.")

    from openbb_cboe.utils.options.data_handler import chain_expirations

    df = data.dataframe.copy()
    expirations = chain_expirations(data)
    symbol = data.underlying_symbol[0]
    price_col = (
        "last_trade_price"
        if "last_trade_price" in df.columns
        else data._identify_price_col(df, "call", "ask")
    )
    target_col_map = {"price": price_col, "iv": "implied_volatility"}
    df.expiration = df.expiration.astype(str)
    base = f"{symbol} {'Implied Volatility' if metric == 'iv' else 'Price'}"

    if strike:
        title = f"{base} @ Strike Nearest To ${strike}"
    elif moneyness:
        title = f"{base} @ {moneyness}% Moneyness"
    else:
        title = f"{base} Nearest OTM Strikes"

    calls = DataFrame()
    puts = DataFrame()

    for expiration in expirations:
        nearest_otm = (
            data._get_nearest_otm_strikes(expiration, moneyness=moneyness)
            if moneyness
            else {}
        )
        call_strike = (
            nearest_otm.get("call")
            if nearest_otm
            else data._get_nearest_strike(
                option_type="call", days=expiration, strike=strike
            )
        )
        put_strike = (
            nearest_otm.get("put")
            if nearest_otm
            else data._get_nearest_strike(
                option_type="put", days=expiration, strike=strike
            )
        )
        calls_filtered = df[
            (df.expiration == expiration)
            & (df.option_type == "call")
            & (df[price_col] > 0)
        ]

        # An expiry with no out-of-the-money strike on a side has no point on that side.
        if call_strike is not None and not calls_filtered.empty:
            calls = concat(
                [
                    calls,
                    calls_filtered.iloc[
                        (calls_filtered.strike - call_strike).abs().argsort()[:1]
                    ],
                ]
            )

        puts_filtered = df[
            (df.expiration == expiration)
            & (df.option_type == "put")
            & (df[price_col] > 0)
        ]

        if put_strike is not None and not puts_filtered.empty:
            puts = concat(
                [
                    puts,
                    puts_filtered.iloc[
                        (puts_filtered.strike - put_strike).abs().argsort()[:1]
                    ],
                ]
            )

    output_df = concat([calls, puts], axis=0).reset_index(drop=True)
    theme = kwargs.get("theme") or "dark"
    fig, text_color, background = new_figure(theme)
    hovertemplate = (
        "$<b>%{y} @ $</b>%{customdata} Strike<extra></extra>"
        if metric == "price"
        else "<b>%{y} @ $</b>%{customdata} Strike<extra></extra>"
    )

    if option_type in ["calls", "both"] and not calls.empty:
        fig.add_scatter(
            x=calls["expiration"],
            y=calls[target_col_map[metric]],
            mode="lines+markers",
            name="Calls",
            marker_color="royalblue",
            hovertemplate=hovertemplate,
            customdata=calls["strike"],
        )

    if option_type in ["puts", "both"] and not puts.empty:
        fig.add_scatter(
            x=puts["expiration"],
            y=puts[target_col_map[metric]],
            mode="lines+markers",
            name="Puts",
            marker_color="red",
            hovertemplate=hovertemplate,
            customdata=puts["strike"],
        )

    fig.set_title(title, x=0.5, font=dict(size=16))
    fig.update_layout(
        paper_bgcolor=background,
        plot_bgcolor=background,
        yaxis=dict(
            ticklen=0,
            showgrid=True,
            tickfont=dict(size=12),
            automargin=True,
            linecolor=text_color,
            showline=True,
        ),
        xaxis=dict(
            showgrid=False,
            tickfont=dict(size=11),
            ticklen=0,
            type="category",
            linecolor=text_color,
            showline=True,
            nticks=10,
            showspikes=False,
        ),
        legend=dict(orientation="v", yanchor="top", y=0.90, xanchor="right", x=-0.01),
        hovermode="x unified",
        font=dict(color=text_color),
        margin=dict(l=10, r=10, t=10, b=10),
    )
    output: Any = OBBject(results=df_to_basemodel(output_df))

    return finalize(output, fig, theme)

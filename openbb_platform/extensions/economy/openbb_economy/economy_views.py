"""Views for the Economy Extension."""

from importlib import import_module
from typing import TYPE_CHECKING, Any
from warnings import warn

if TYPE_CHECKING:
    from openbb_charting.core.openbb_figure import (
        OpenBBFigure,
    )


class EconomyViews:
    """economy Views."""

    @staticmethod
    def economy_fred_series(
        **kwargs,
    ) -> tuple["OpenBBFigure", dict[str, Any]]:
        """FRED Series Chart."""
        from openbb_core.app.utils import basemodel_to_df
        from pandas import DataFrame

        bar_chart = import_module("openbb_charting.charts.generic_charts").bar_chart
        z_score_standardization = import_module(
            "openbb_charting.charts.helpers"
        ).z_score_standardization
        ChartStyle = import_module("openbb_charting.core.chart_style").ChartStyle
        OpenBBFigure = import_module("openbb_charting.core.openbb_figure").OpenBBFigure
        LARGE_CYCLER = import_module("openbb_charting.styles.colors").LARGE_CYCLER

        ytitle_dict = {
            "chg": "Change",
            "ch1": "Change From Year Ago",
            "pch": "Percent Change",
            "pc1": "Percent Change From Year Ago",
            "pca": "Compounded Annual Rate Of Change",
            "cch": "Continuously Compounded Rate Of Change",
            "cca": "Continuously Compounded Annual Rate Of Change",
            "log": "Natural Log",
        }

        provider = kwargs.get("provider")

        if provider != "fred":
            raise RuntimeError(
                f"This charting method does not support {provider}. Supported providers: fred."
            )

        columns = basemodel_to_df(kwargs["obbject_item"], index=None).columns.to_list()

        allow_unsafe = kwargs.get("allow_unsafe", False)
        dropnan = kwargs.get("dropna", True)
        normalize = kwargs.get("normalize", False)

        data_cols = []
        data = kwargs.get("data")

        if isinstance(data, DataFrame) and not data.empty:
            data_cols = data.columns.to_list()
            df_ta = data

        else:
            df_ta = basemodel_to_df(kwargs["obbject_item"], index="date")

        # Check for unsupported external data injection.
        if allow_unsafe is False and data_cols:
            for data_col in data_cols:
                if data_col not in columns:
                    raise RuntimeError(
                        f"Column '{data_col}' was not found in the original data."
                        + " External data injection is not supported unless `allow_unsafe = True`."
                    )

        # Align the data so each column has the same index and length.
        if dropnan:
            df_ta = df_ta.dropna(how="any")

        if df_ta.empty or len(df_ta) < 2:
            raise ValueError(
                "No data is left after dropping NaN values. Try setting `dropnan = False`,"
                + " or use the `frequency` parameter on request."
            )

        columns = df_ta.columns.to_list()

        metadata = kwargs["extra"].get("results_metadata", {})

        # Check if the request was transformed by the FRED API.
        params = kwargs["extra_params"] if kwargs.get("extra_params") else {}
        has_params = hasattr(params, "transform") and params.transform is not None

        # Get a unique list of all units of measurement in the DataFrame.
        y_units = list(
            {metadata.get(col).get("units") for col in columns if col in metadata}
        )
        if has_params is True and not y_units:
            y_units = [ytitle_dict.get(params.transform)]  # ty: ignore[unresolved-attribute]

        if normalize or (
            kwargs.get("bar") is True
            and len(y_units) > 1
            and (
                has_params is False
                or not any(
                    i in params.transform  # ty: ignore[unresolved-attribute]
                    for i in ["pc1", "pch", "pca", "cch", "cca", "log"]
                )
            )
        ):
            normalize = True
            df_ta = df_ta.apply(z_score_standardization)

        if len(y_units) > 2 and has_params is False and allow_unsafe is False:
            raise RuntimeError(
                "This method supports up to 2 y-axis units."
                + " Please use the 'transform' parameter, in the data request,"
                + " to compare all series on the same scale, or set `normalize = True`."
                + " Override this error by setting `allow_unsafe = True`."
            )

        y1_units = y_units[0] if y_units else None
        y1title = y1_units
        y2title = y_units[1] if len(y_units) > 1 else None
        xtitle = str(kwargs.get("xtitle", ""))

        # If the request was transformed, the y-axis will be shared under these conditions.
        if has_params and any(
            i in params.transform  # ty: ignore[unsupported-operator]
            for i in ["pc1", "pch", "pca", "cch", "cca", "log"]
        ):
            y1title = "Log" if params.transform == "Log" else "Percent"
            y2title = None

        # Set the title for the chart.
        title: str = ""
        if isinstance(kwargs, dict) and title in kwargs:
            title = kwargs["title"]
        else:
            if metadata.get(columns[0]):
                title = (
                    metadata.get(columns[0]).get("title")
                    if len(columns) == 1
                    else "FRED Series"
                )
            else:
                title = "FRED Series"
            transform_title = (
                ytitle_dict.get(params.transform)  # ty: ignore[unresolved-attribute]
                if has_params is True
                else ""
            )
            title = f"{title} - {transform_title}" if transform_title else title

        # Define this to use as a check.
        y3title: str | None = ""

        if kwargs.get("plot_bar") is True or len(df_ta.index) < 100:
            margin = dict(l=10, r=5, b=75 if xtitle else 30)
            try:
                if normalize:
                    y1title = None
                    title = f"{title} - Normalized" if title else "Normalized"
                bar_mode = kwargs.get("barmode", "group")
                fig = bar_chart(
                    df_ta.reset_index(),
                    "date",
                    df_ta.columns.to_list(),
                    title=title,
                    xtitle=xtitle,
                    ytitle=y1title,
                    barmode=bar_mode,
                    layout_kwargs=dict(margin=margin),
                )
                if kwargs.get("layout_kwargs"):
                    fig.update_layout(kwargs.get("layout_kwargs"))

                if kwargs.get("title"):
                    fig.set_title(str(kwargs.get("title")))  # ty: ignore[unresolved-attribute]

                content = fig.to_plotly_json()

                return fig, content  # ty: ignore[invalid-return-type]
            except Exception as _:
                warn("Bar chart failed. Attempting line chart.")

        # Create the figure object with subplots.
        fig = OpenBBFigure().create_subplots(
            rows=1, cols=1, shared_xaxes=True, shared_yaxes=False
        )
        fig.update_layout(ChartStyle().plotly_template.get("layout", {}))
        text_color = "white" if ChartStyle().plt_style == "dark" else "black"
        # For each series in the DataFrame, add a scatter plot.
        for i, col in enumerate(df_ta.columns):
            # Check if the y-axis should be shared for this series.
            on_y1 = (
                (
                    metadata.get(col).get("units") == y1_units
                    or y2title is None
                    or kwargs.get("same_axis") is True
                )
                if metadata.get(col)
                else False
            )
            if normalize:
                on_y1 = True

            yaxes = "y2" if not on_y1 else "y1"
            on_y3 = not metadata.get(col) and normalize is False
            if on_y3:
                yaxes = "y3"
                y3title = df_ta[col].name
            fig.add_scatter(
                x=df_ta.index,
                y=df_ta[col],
                name=df_ta[col].name,
                mode="lines",
                hovertemplate=f"{df_ta[col].name}: %{{y}}<extra></extra>",
                line=dict(width=2, color=LARGE_CYCLER[i % len(LARGE_CYCLER)]),
                yaxis="y1" if kwargs.get("same_axis") is True else yaxes,
            )

        # Set the y-axis titles, if supplied.
        if kwargs.get("y1title"):
            y1title = kwargs.get("y1title")
        if kwargs.get("y2title") and y2title is not None:
            y2title = kwargs.get("y2title")
        # Set the x-axis title, if suppiled.
        if isinstance(kwargs, dict) and "xtitle" in kwargs:
            xtitle = kwargs["xtitle"]
        # If the data was normalized, set the title to reflect this.
        if normalize:
            y1title = None
            y2title = None
            y3title = None
            title = f"{title} - Normalized" if title else "Normalized"

        # Now update the layout of the complete figure.
        fig.update_layout(
            title=dict(text=title, x=0.5, font=dict(size=16)),
            legend=dict(
                orientation="h",
                yanchor="bottom",
                xanchor="right",
                y=1.02,
                x=0.95,
                bgcolor=(
                    "rgba(0,0,0,0)" if text_color == "white" else "rgba(255,255,255,0)"
                ),
                font=dict(size=12),
            ),
            yaxis=(
                dict(
                    ticklen=0,
                    side="right",
                    showline=True,
                    mirror=True,
                    title=dict(text=y1title, standoff=30, font=dict(size=16)),
                    tickfont=dict(size=14),
                    anchor="x",
                    gridcolor="rgba(128,128,128,0.3)",
                )
                if y1title
                else None
            ),
            yaxis2=(
                dict(
                    overlaying="y",
                    side="left",
                    ticklen=0,
                    showgrid=False,
                    title=dict(
                        text=y2title if y2title else None,
                        standoff=10,
                        font=dict(size=16),
                    ),
                    tickfont=dict(size=14),
                    anchor="x",
                )
                if y2title
                else None
            ),
            yaxis3=(
                dict(
                    overlaying="y",
                    side="left",
                    ticklen=0,
                    position=0,
                    showgrid=False,
                    showticklabels=True,
                    title=(
                        dict(text=y3title, standoff=10, font=dict(size=16))
                        if y3title
                        else None
                    ),
                    tickfont=dict(size=12, color="rgba(128,128,128,0.9)"),
                    anchor="free",
                )
                if y3title
                else None
            ),
            xaxis=dict(
                ticklen=0,
                showgrid=True,
                showline=True,
                mirror=True,
                title=(
                    dict(text=xtitle, standoff=30, font=dict(size=16))
                    if xtitle
                    else None
                ),
                gridcolor="rgba(128,128,128,0.3)",
                domain=[0.095, 0.95] if y3title else None,
            ),
            margin=(
                dict(r=25, l=25, b=75 if xtitle else 30) if normalize is False else None
            ),
            font=dict(color=text_color),
            autosize=True,
            dragmode="pan",
        )
        if kwargs.get("layout_kwargs"):
            fig.update_layout(kwargs.get("layout_kwargs"))
        if kwargs.get("title"):
            fig.set_title(str(kwargs.get("title")))

        content = fig.to_plotly_json()

        return fig, content

    @staticmethod
    def economy_survey_bls_series(
        **kwargs,
    ) -> tuple["OpenBBFigure", dict[str, Any]]:
        """Economy Survey BLS Series Chart.

        Parameters
        ----------
        data: Optional[Union[DataFrame, List[Data]]]
            Filtered subset of the parent results.
        target_symbol: Optional[str]
            The target symbol(s) to plot. Plot multiple symbols by separating them with a comma. Max 10 symbols.
        target_col: Optional[str]
            The target column to plot. Default is 'value'.
        plot_type: Literal["line", "bar"]
            The type of plot to display. Default is 'line', unless the data is significantly small.
        normalize: bool
            Normalize the data before displaying. Default is False.
        title: Optional[str]
            The title of the chart.
        xtitle: Optional[str]
            The title of the x-axis.
        ytitle: Optional[str]
            The title of the y-axis.
        bar_kwargs: Optional[dict]
            Additional keyword arguments applied to `fig.add_bar`.
        scatter_kwargs: Optional[dict]
            Additional keyword arguments applied to `fig.add_scatter`.
        layout_kwargs: Optional[dict]
            Additional keyword arguments applied to `fig.update_layout`.
        """
        from openbb_core.app.utils import basemodel_to_df
        from pandas import DataFrame

        _generic_charts = import_module("openbb_charting.charts.generic_charts")
        bar_chart = _generic_charts.bar_chart
        line_chart = _generic_charts.line_chart
        z_score_standardization = import_module(
            "openbb_charting.charts.helpers"
        ).z_score_standardization

        provider = kwargs.get("provider")

        if provider != "bls":
            raise RuntimeError(
                f"This charting method does not support {provider}. Supported providers: bls."
            )

        _data = (
            kwargs.pop("data", None)
            if "data" in kwargs and kwargs["data"] is not None
            else kwargs.get("obbject_item")
        )
        df = DataFrame()

        if isinstance(_data, DataFrame) and not _data.empty:
            df = _data.reset_index() if _data.index.name == "date" else _data
        else:
            try:
                df = basemodel_to_df(_data, index=None)  # ty: ignore[invalid-argument-type]
            except Exception as e:
                raise RuntimeError("Unable to process supplied data.") from e

        if df.empty or len(df) < 2:
            raise RuntimeError("No data found to plot.")

        cols = df.columns.to_list()
        target_col = kwargs.get("target_col", "value")
        if target_col not in cols:
            raise RuntimeError(f"Column '{target_col}' not found in the data.")

        new_df = df.pivot(columns="symbol", values=target_col, index="date")
        target_symbols = kwargs.get("target_symbol", "").split(",")[:10]

        if not target_symbols or len(target_symbols) == 0 or target_symbols[0] == "":
            target_symbols = new_df.columns.to_list()[:10]

        metadata = kwargs["extra"].get("results_metadata", {})
        ytitle = kwargs.get("ytitle", "")

        new_df = new_df.filter(target_symbols, axis=1)

        if "percent" in target_col.lower():
            ytitle = (
                ytitle
                if ytitle
                else target_col.replace("change_percent_", "").replace("M", " Month")
                + " Change (%)"
            )
            new_df = new_df.apply(lambda x: x * 100)
        elif "change" in target_col.lower() and "percent" not in target_col.lower():
            ytitle = (
                ytitle
                if ytitle
                else target_col.replace("change_", "").replace("M", " Month")
                + " Change"
            )

        title_map: dict = {}
        for symbol in target_symbols:
            if symbol not in new_df.columns:
                continue
            survey_name = metadata.get(symbol, {}).get("survey_name", symbol)
            series_title = metadata.get(symbol, {}).get("series_title", symbol)

            if survey_name != series_title:
                title_map[symbol] = f"{survey_name} \n    {series_title}"

        normalize = kwargs.get("normalize", False)
        same_axis = kwargs.get("same_axis", False)

        if normalize:
            new_df = new_df.apply(z_score_standardization)
            same_axis = True
            if ytitle:
                ytitle = f"Normalized {ytitle.replace('(%)', '')}"

        plot_type = kwargs.get("plot_type")

        if plot_type is None:
            plot_type = (
                "line"
                if (len(new_df.index) > 36 and len(new_df.columns.to_list()) >= 1)
                else "bar"
            )

        layout_kwargs: dict = kwargs.pop("layout_kwargs", {})
        scatter_kwargs: dict = kwargs.pop("scatter_kwargs", {})
        bar_kwargs: dict = kwargs.pop("bar_kwargs", {})
        hovertemplate = scatter_kwargs.pop("hovertemplate", None)
        trace_titles = {
            symbol: metadata.get(symbol, {})
            .get("series_title", symbol)
            .replace(",", " -")
            for symbol in target_symbols
        }
        new_df.columns = [trace_titles.get(col, col) for col in new_df.columns]
        scatter_kwargs["hovertemplate"] = (
            hovertemplate if hovertemplate else "%{fullData.name}:%{y}<extra></extra>"
        )

        if len(target_symbols) == 1:
            title = title_map.get(target_symbols[0], target_symbols[0])
            fig = (
                line_chart(
                    data=new_df,
                    title=title,
                    ytitle=ytitle,
                    y=list(trace_titles.values()),
                    scatter_kwargs=scatter_kwargs,
                    layout_kwargs=layout_kwargs,
                    **kwargs,
                )
                if plot_type == "line"
                else bar_chart(
                    data=new_df,
                    title=title,
                    ytitle=ytitle,
                    x=new_df.index,
                    y=list(trace_titles.values()),
                    layout_kwargs=layout_kwargs,
                    bar_kwargs=bar_kwargs,
                    **kwargs,
                )
            )
        else:
            survey_name = (
                metadata.get(target_symbols[0], {})
                .get("survey_name", target_symbols[0])
                .split("\n")[0]
                .strip()
            )
            _t = kwargs.pop("title", None)
            title = _t if _t else f"{survey_name} - {ytitle}" if ytitle else survey_name
            fig = (
                line_chart(
                    data=new_df,
                    y=list(trace_titles.values()),
                    title=title,
                    ytitle=ytitle,
                    same_axis=same_axis,
                    normalize=False,
                    scatter_kwargs=scatter_kwargs,
                    layout_kwargs=layout_kwargs,
                    **kwargs,
                )
                if plot_type == "line"
                else bar_chart(
                    data=new_df,
                    title=title,
                    ytitle=ytitle,
                    x=new_df.index,
                    y=list(trace_titles.values()),
                    layout_kwargs=layout_kwargs,
                    bar_kwargs=bar_kwargs,
                    **kwargs,
                )
            )

        fig.update_layout(
            margin=dict(b=20),
            legend=dict(
                orientation="h",
                yanchor="top",
                xanchor="left",
                y=-0.075,
                x=0,
                font=dict(size=12),
            ),
        )
        content = fig.to_plotly_json()

        return fig, content  # ty: ignore[invalid-return-type]

    @staticmethod
    def economy_shipping_chokepoint_info(
        **kwargs,
    ) -> tuple["OpenBBFigure", dict[str, Any]]:
        """Maritime Chokepoint Info Chart."""
        provider = kwargs.get("provider")

        if provider != "imf":
            raise RuntimeError(
                f"This charting method does not support {provider}. Supported providers: imf."
            )

        try:
            plot_chokepoint_annual_avg_vessels = import_module(
                "openbb_imf.views.maritime_chokepoint_info"
            ).plot_chokepoint_annual_avg_vessels
        except Exception as e:
            raise RuntimeError("Unable to import the required module.") from e

        theme = (
            kwargs.get("extra_params", {}).get("theme")
            or kwargs.get("theme")
            or getattr(kwargs["charting_settings"], "chart_style", "dark")
        )
        data = (
            kwargs.pop("data")
            if "data" in kwargs and kwargs["data"] is not None
            else kwargs["obbject_item"]
        )
        fig = plot_chokepoint_annual_avg_vessels(data, theme=theme)
        fig.update_layout(
            margin=dict(l=25, r=25, t=50, b=0),
        )
        content = fig.to_plotly_json()

        content["config"] = dict(responsive=False)

        return fig, content

    @staticmethod
    def economy_shipping_port_info(
        **kwargs,
    ) -> tuple["OpenBBFigure", dict[str, Any]]:
        """Port Info Chart."""
        provider = kwargs.get("provider")

        if provider != "imf":
            raise RuntimeError(
                f"This charting method does not support {provider}. Supported providers: imf."
            )

        try:
            plot_port_info_map = import_module(
                "openbb_imf.views.port_info"
            ).plot_port_info_map
        except Exception as e:
            raise RuntimeError("Unable to import the required module.") from e

        data = (
            kwargs.pop("data")
            if "data" in kwargs and kwargs["data"] is not None
            else kwargs["obbject_item"]
        )
        fig = plot_port_info_map(data)
        fig.update_layout(
            margin=dict(l=0, r=0, t=0, b=0),
        )
        content = fig.to_plotly_json()

        content["config"] = dict(
            responsive=False,
            displayModeBar=False,
            dragMode="pan",
            doubleClick="reset",
        )

        return fig, content

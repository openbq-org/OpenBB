"""OpenBB Figure Class."""

import json
import textwrap
from datetime import datetime, timedelta
from math import floor
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    TypeVar,
    Union,
    cast,
)
from warnings import warn

import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots

from openbb_charting.core.backend import Backend
from openbb_charting.core.config.openbb_styles import (
    PLT_TBL_ROW_COLORS,
)

if TYPE_CHECKING:
    from numpy import ndarray
    from openbb_core.app.model.charts.charting_settings import ChartingSettings
    from pandas import DataFrame, Series

    try:  # noqa: SIM105
        # noqa: F401
        from darts import TimeSeries
    except ImportError:
        pass

TimeSeriesT = TypeVar("TimeSeriesT", bound="TimeSeries")

pio.default_renderers = "notebook"  # ty: ignore[unresolved-attribute]


class OpenBBFigure(go.Figure):
    """Custom Figure class for OpenBB Terminal.

    Parameters
    ----------
    fig : `go.Figure`, optional
        Figure to copy, by default None
    **kwargs
        Keyword arguments to pass to `go.Figure.update_layout`

    Attributes
    ----------
    has_subplots : `bool`
        Whether the figure has subplots
    """

    def __init__(self, fig: go.Figure | None = None, **kwargs) -> None:
        """Initialize the OpenBBFigure."""
        from openbb_charting.core.chart_style import ChartStyle

        super().__init__()
        if fig:
            self.__dict__ = (
                go.Figure(fig).__dict__ if isinstance(fig, dict) else fig.__dict__
            )

        self._charting_settings: ChartingSettings | None = kwargs.pop(
            "charting_settings", None
        )
        self._has_secondary_y = kwargs.pop("has_secondary_y", False)
        self._subplots_kwargs: dict[str, Any] = kwargs.pop("subplots_kwargs", {})
        self._multi_rows = kwargs.pop("multi_rows", False)
        self._added_logscale = False
        self._date_xaxs: dict = {}
        self._margin_adjusted = False
        self._feature_flags_applied = False
        self._cmd_xshift = 0
        self._bar_width = 0.15
        self._subplot_xdates: dict[int, dict[int, list[Any]]] = {}

        if kwargs.pop("create_backend", False) and self._charting_settings:
            Backend(self._charting_settings)
        self._theme = ChartStyle(
            getattr(self._charting_settings, "plt_style", ""),
            getattr(self._charting_settings, "user_styles_directory", None),
        )

        if xaxis := kwargs.pop("xaxis", None):
            self.update_xaxes(xaxis)
        if yaxis := kwargs.pop("yaxis", None):
            self.update_yaxes(yaxis)

        self.update_layout(**kwargs)

        self._backend = Backend.instance

    @property
    def theme(self):
        """Theme property."""
        return self._theme

    @property
    def subplots_kwargs(self):
        """Get subplots kwargs property."""
        return self._subplots_kwargs

    @subplots_kwargs.setter
    def subplots_kwargs(self, value):
        """Get subplots kwargs setter."""
        self._subplots_kwargs = value

    @property
    def has_subplots(self):
        """Has subplots property."""
        return self._has_subplots()

    @property
    def bar_width(self):
        """Bar width property."""
        return self._bar_width

    @bar_width.setter
    def bar_width(self, value):
        """Bar width setter."""
        self._bar_width = value

    @property
    def cmd_xshift(self):
        """Command line x shift property."""
        return self._cmd_xshift

    @cmd_xshift.setter
    def cmd_xshift(self, value):
        """Command line x shift setter."""
        self._cmd_xshift = value

    @classmethod
    def create_subplots(
        cls,
        rows: int = 1,
        cols: int = 1,
        shared_xaxes: bool = True,
        vertical_spacing: float | None = None,
        horizontal_spacing: float | None = None,
        subplot_titles: list[str] | tuple | None = None,
        row_width: list[float | int] | None = None,
        specs: list[list[dict[Any, Any] | None]] | None = None,
        **kwargs,
    ) -> "OpenBBFigure":
        """Create a new Plotly figure with subplots.

        Parameters
        ----------
        rows : `int`, optional
            Number of rows, by default 1
        cols : `int`, optional
            Number of columns, by default 1
        shared_xaxes : `bool`, optional
            Whether to share x axes, by default True
        vertical_spacing : `float`, optional
            Vertical spacing between subplots, by default None
        horizontal_spacing : `float`, optional
            Horizontal spacing between subplots, by default None
        subplot_titles : `Union[List[str], tuple]`, optional
            Titles for each subplot, by default None
        row_width : `List[Union[float, int]]`, optional
            Width of each row, by default [1]
        specs : `List[List[dict]]`, optional
            Subplot specs, by default `[[{}] * cols] * rows` (all subplots are the same size)
        """
        subplots_kwargs = dict(
            rows=rows,
            cols=cols,
            shared_xaxes=shared_xaxes,
            vertical_spacing=vertical_spacing,
            horizontal_spacing=horizontal_spacing,
            subplot_titles=subplot_titles,
            row_width=row_width or [1] * rows,
            specs=specs or [[{}] * cols] * rows,
            **kwargs,
        )

        fig = make_subplots(**subplots_kwargs)

        kwargs = {
            "multi_rows": rows > 1,
            "subplots_kwargs": subplots_kwargs,
        }
        if specs and any(
            spec.get("secondary_y", False) for row in specs for spec in row if spec
        ):
            kwargs["has_secondary_y"] = True

        return cls(fig, **kwargs)

    def add_trend(
        self,
        data: "DataFrame",
        row: int = 1,
        col: int = 1,
        secondary_y: bool = False,
        **kwargs,
    ):
        """Add a trend line to the figure.

        Parameters
        ----------
        data : `DataFrame`
            Data to plot
        row : `int`, optional
            Row number, by default 1
        col : `int`, optional
            Column number, by default 1
        secondary_y : `bool`, optional
            Whether to plot on secondary y axis, by default None
        """
        try:
            for column, color in zip(
                ["OC_High_trend", "OC_Low_trend"],
                [self._theme.up_color, self._theme.down_color],
            ):
                if column in data.columns:
                    name = column.split("_")[1].title()
                    trend = data.copy().dropna()
                    self.add_shape(
                        type="line",
                        name=f"{name} Trend",
                        x0=trend.index[0],
                        y0=trend[column].iloc[0],
                        x1=trend.index[-1],
                        y1=trend[column].iloc[-1],
                        line=dict(color=color, width=2),
                        row=row,
                        col=col,
                        secondary_y=secondary_y,
                        **kwargs,
                    )

        except Exception as e:
            raise ValueError(f"Error adding trend line: {e}") from e

    def add_histplot(
        self,
        dataset: Union["ndarray", "Series", TimeSeriesT],
        name: str | list[str] | None = None,
        colors: list[str] | None = None,
        bins: int | str = 15,
        curve: Literal["normal", "kde"] = "normal",
        show_curve: bool = True,
        show_rug: bool = True,
        show_hist: bool = True,
        forecast: bool = False,
        row: int = 1,
        col: int = 1,
    ) -> None:
        """Add a histogram with a curve and rug plot if desired.

        Parameters
        ----------
        dataset : `Union[ndarray, Series, TimeSeriesT]`
            Data to plot
        name : `Optional[Union[str, List[str]]]`, optional
            Name of the plot, by default None
        colors : `Optional[List[str]]`, optional
            Colors of the plot, by default None
        bins : `Union[int, str]`, optional
            Number of bins, by default 15
        curve : `Literal["normal", "kde"]`, optional
            Type of curve to plot, by default "normal"
        show_curve : `bool`, optional
            Whether to show the curve, by default True
        show_rug : `bool`, optional
            Whether to show the rug plot, by default True
        show_hist : `bool`, optional
            Whether to show the histogram, by default True
        forecast : `bool`, optional
            Whether the data is a darts forecast TimeSeries, by default False
        row : `int`, optional
            Row of the subplot, by default 1
        col : `int`, optional
            Column of the subplot, by default 1
        """
        from numpy import linspace, mean, ndarray, std
        from pandas import Series
        from scipy import stats

        callback = stats.norm if curve == "normal" else stats.gaussian_kde

        def _validate_x(data: ndarray | Series | type[TimeSeriesT]):
            if forecast:  # pragma: no cover - darts forecast path (darts is an optional dependency)
                data = data.univariate_values()  # ty: ignore[unresolved-attribute]
            if isinstance(data, Series):
                data = data.to_numpy()
            if isinstance(data, ndarray):
                data = data.tolist()
            if isinstance(data, list):
                data = [data]  # ty: ignore[invalid-assignment]

            return data

        valid_x = _validate_x(dataset)

        if isinstance(name, str):
            name = [name]

        if isinstance(colors, str):
            colors = [colors]
        if not name:
            name = [None] * len(valid_x)  # ty: ignore[invalid-assignment]
        if not colors:
            colors = [None] * len(valid_x)  # ty: ignore[invalid-assignment]

        max_y = 0
        for i, (x_i, name_i, color_i) in enumerate(zip(valid_x, name, colors)):  # ty: ignore[invalid-argument-type, not-iterable]
            if not color_i:
                color_i = (  # noqa: PLW2901
                    self._theme.up_color if i % 2 == 0 else self._theme.down_color
                )

            res_mean, res_std = mean(x_i), std(x_i)
            res_min, res_max = min(x_i), max(x_i)
            x = linspace(res_min, res_max, 100)
            if show_hist:
                if forecast:  # pragma: no cover - darts forecast path (darts is an optional dependency)
                    components = list(dataset.components[:4])  # ty: ignore[unresolved-attribute]
                    values = (
                        cast("TimeSeries", dataset)[components]
                        .all_values(copy=False)
                        .flatten(order="F")
                    )
                    n_components = len(components)
                    n_entries = len(values) // n_components
                    for i2, label in zip(range(n_components), components):
                        self.add_histogram(
                            x=values[i2 * n_entries : (i2 + 1) * n_entries],  # noqa: E203  # noqa: E203
                            name=label,
                            marker_color=color_i,
                            nbinsx=bins,
                            opacity=0.7,
                            row=row,
                            col=col,
                        )
                else:
                    self.add_histogram(
                        x=x_i,
                        name=name_i,
                        marker_color=color_i,
                        nbinsx=bins,
                        histnorm="probability density",
                        histfunc="sum",
                        opacity=0.7,
                        row=row,
                        col=col,
                    )

            if show_rug:
                self.add_scatter(
                    x=x_i,
                    y=[0.00002] * len(x_i),
                    name=name_i if len(name) < 2 else name[1],  # ty: ignore[invalid-argument-type, not-subscriptable]
                    mode="markers",
                    marker=dict(
                        color=self._theme.down_color,
                        symbol="line-ns-open",
                        size=10,
                    ),
                    row=row,
                    col=col,
                )
            if show_curve:
                if curve == "kde":
                    curve_x = [None] * len(valid_x)
                    curve_y = [None] * len(valid_x)
                    for index in range(len(valid_x)):
                        curve_x[index] = [
                            res_min + xx * (res_max - res_min) / 500
                            for xx in range(500)
                        ]
                        curve_y[index] = stats.gaussian_kde(valid_x[index])(
                            curve_x[index]
                        )
                    for index in range(len(valid_x)):
                        self.add_scatter(
                            x=curve_x[index],
                            y=curve_y[index],
                            name=name_i,
                            mode="lines",
                            showlegend=False,
                            marker=dict(color=color_i),
                            row=row,
                            col=col,
                        )
                        max_y = max(max_y, max(curve_y[index]) * 1.2)  # ty: ignore[invalid-argument-type]

                else:
                    y = (
                        callback(res_mean, res_std).pdf(x)
                        * len(valid_x[0])
                        * (res_max - res_min)
                        / bins
                    )

                    self.add_scatter(
                        x=x,
                        y=y,
                        name=name_i,
                        mode="lines",
                        marker=dict(color=color_i),
                        showlegend=False,
                        row=row,
                        col=col,
                    )

                    max_y = max(max_y, y * 2)

        self.update_yaxes(
            position=0.0,
            range=[0, max_y],
            row=row,
            col=col,
            automargin=False,
            autorange=False,
        )

        self.update_layout(barmode="overlay", bargap=0.01, bargroupgap=0)

    def set_title(
        self, title: str, wrap: bool = False, wrap_width: int = 80, **kwargs
    ) -> "OpenBBFigure":
        """Set the main title of the figure.

        Parameters
        ----------
        title : `str`
            Title of the figure
        wrap : `bool`
            If True, the title will be wrapped according to the wrap_width parameter
        wrap_width : `int`
            Width in characters to wrap the title if wrap is True, default is 80
        """
        if wrap:
            title = "<br>".join(textwrap.wrap(title, width=wrap_width))

        if kwargs.get("row") is not None and kwargs.get("col") is not None:
            self.add_annotation(
                text=title,
                xref="x domain",
                yref="y domain",
                x=0.5,
                y=1.0,
                xanchor="center",
                yanchor="bottom",
                **kwargs,
            )
            return self

        self.update_layout(title=dict(text=title, **kwargs))
        return self

    def set_xaxis_title(
        self,
        title: str,
        row: int | None = None,
        col: int | None = None,
        **kwargs,
    ) -> "OpenBBFigure":
        """Set the x axis title of the figure or subplot (if row and col are specified).

        Parameters
        ----------
        title : `str`
            Title of the x axis
        row : `int`, optional
            Row number, by default None
        col : `int`, optional
            Column number, by default None
        """
        self.update_xaxes(title=title, row=row, col=col, **kwargs)
        return self

    def set_yaxis_title(
        self, title: str, row: int | None = None, col: int | None = None, **kwargs
    ) -> "OpenBBFigure":
        """Set the y axis title of the figure or subplot (if row and col are specified).

        Parameters
        ----------
        title : `str`
            Title of the x axis
        row : `int`, optional
            Row number, by default None
        col : `int`, optional
            Column number, by default None
        """
        self.update_yaxes(title=title, row=row, col=col, **kwargs)
        return self

    def add_hline_legend(
        self,
        y: float,
        name: str,
        line: dict | None = None,
        legendrank: int | None = None,
        **kwargs,
    ) -> None:
        """Add a horizontal line with a legend label.

        Parameters
        ----------
        y : `float`
            y value of the line
        name : `str`
            Name of the to display in the legend
        line : `dict`
            Line style
        legendrank : `int`, optional
            Legend rank, by default None (e.g. 1 is above 2)
        """
        if line is None:
            line = {}

        self.add_hline(
            y,
            line=line,
        )
        self.add_legend_label(
            label=name,
            mode="lines",
            line_dash=line.get("dash", "solid"),
            marker=dict(color=line.get("color", self._theme.line_color)),
            legendrank=legendrank,
            **kwargs,
        )

    def add_vline_legend(
        self,
        x: float,
        name: str,
        line: dict | None = None,
        legendrank: int | None = None,
        **kwargs,
    ) -> None:
        """Add a vertical line with a legend label.

        Parameters
        ----------
        x : `float`
            x value of the line
        name : `str`
            Name of the to display in the legend
        line : `dict`
            Line style
        legendrank : `int`, optional
            Legend rank, by default None (e.g. 1 is above 2)
        """
        if line is None:
            line = {}

        self.add_vline(
            x,
            line=line,
        )
        self.add_legend_label(
            label=name,
            mode="lines",
            line_dash=line.get("dash", "solid"),
            marker=dict(color=line.get("color", self._theme.line_color)),
            legendrank=legendrank,
            **kwargs,
        )

    def horizontal_legend(  # noqa: PLR0913
        self,
        x: float = 1,
        y: float = 1.02,
        xanchor: str = "right",
        yanchor: str = "bottom",
        orientation: str = "h",
        **kwargs,
    ) -> None:
        """Set the legend to be horizontal.

        Parameters
        ----------
        x : `float`, optional
            The x position of the legend, by default 1
        y : `float`, optional
            The y position of the legend, by default 1.02
        xanchor : `str`, optional
            The x anchor of the legend, by default "right"
        yanchor : `str`, optional
            The y anchor of the legend, by default "bottom"
        orientation : `str`, optional
            The orientation of the legend, by default "h"
        """
        self.update_layout(
            legend=dict(
                x=x,
                y=y,
                xanchor=xanchor,
                yanchor=yanchor,
                orientation=orientation,
                **kwargs,
            )
        )

    @staticmethod
    def chart_volume_scaling(
        df_volume: "DataFrame", volume_ticks_x: int = 7
    ) -> dict[str, list]:
        """Take df_volume and returns volume_ticks, tickvals for chart volume scaling.

        Parameters
        ----------
        df_volume : DataFrame
            Dataframe of volume (e.g. df_volume = df["volume"])
        volume_ticks_x : int, optional
            Number to multiply volume, by default 7

        Returns
        -------
        Dict[str, list]
            {"range": volume_range, "ticks": tickvals}
        """
        from pandas import Series, to_numeric

        df_volume = df_volume.apply(lambda x: f"{x:.1f}")
        df_volume = to_numeric(df_volume.astype(float))

        if isinstance(df_volume, Series):
            df_volume = df_volume.to_frame()

        volume_ticks = int(df_volume.max().max())
        round_digits = -3
        first_val = round(volume_ticks * 0.20, round_digits)

        for x, y in zip([2, 5, 6, 7, 8, 9, 10], [1, 4, 5, 6, 7, 8, 9]):
            if len(str(volume_ticks)) > x:
                round_digits = -y
                first_val = round(volume_ticks * 0.20, round_digits)

        tickvals = [
            floor(first_val),
            floor(first_val * 2),
            floor(first_val * 3),
            floor(first_val * 4),
        ]
        volume_range = [0, floor(volume_ticks * volume_ticks_x)]

        return {"range": volume_range, "ticks": tickvals}

    def add_inchart_volume(  # noqa: PLR0913
        self,
        df_stock: "DataFrame",
        close_col: str | None = "close",
        volume_col: str | None = "volume",
        row: int | None = 1,
        col: int | None = 1,
        volume_ticks_x: int = 7,
    ) -> None:
        """Add in-chart volume to a subplot.

        Parameters
        ----------
        df_stock : `DataFrame`
            Dataframe of the stock
        close_col : `str`, optional
            Name of the close column, by default "close"
        volume_col : `str`, optional
            Name of the volume column, by default "volume"
        row : `int`, optional
            Row number, by default 2
        col : `int`, optional
            Column number, by default 1
        volume_ticks_x : int, optional
            Number to multiply volume, by default 7
        """
        from numpy import where

        colors = where(
            df_stock.open < df_stock[close_col],
            self._theme.up_color,
            self._theme.down_color,
        )
        vol_scale = self.chart_volume_scaling(df_stock[volume_col], volume_ticks_x)
        self.add_bar(
            x=df_stock.index,
            y=df_stock[volume_col],
            name="Volume",
            marker_color=colors,
            yaxis="y2",
            row=row,
            col=col,
            opacity=0.5,
            secondary_y=True,
            showlegend=False,
            hovertemplate="%{y}<extra></extra>",
        )
        ticksize = 13 - (self.subplots_kwargs["rows"] // 2)
        self.update_layout(
            yaxis2=dict(
                fixedrange=False,
                side="left",
                nticks=8,
                autorange=False,
                range=vol_scale["range"],
                tickvals=vol_scale["ticks"],
                showgrid=False,
                showline=False,
                zeroline=False,
                tickfont=dict(size=ticksize),
                overlaying="y",
            ),
            yaxis=dict(
                autorange=True,
                automargin=True,
                side="right",
                fixedrange=False,
                anchor="x",
                layer="above traces",
            ),
        )

    def add_legend_label(  # noqa: PLR0913
        self,
        trace: str | None = None,
        label: str | None = None,
        mode: str | None = None,
        marker: dict | None = None,
        line_dash: str | None = None,
        legendrank: int | None = None,
        **kwargs,
    ) -> None:
        """Add a legend label.

        Parameters
        ----------
        trace : `str`, optional
            The name of the trace to use as a template, by default None
        label : `str`, optional
            The label to use, by default None (uses the trace name if trace is specified)
            If trace is not specified, label must be specified
        mode : `str`, optional
            The mode to use, by default "lines" (uses the trace mode if trace is specified)
        marker : `dict`, optional
            The marker to use, by default dict() (uses the trace marker if trace is specified)
        line_dash : `str`, optional
            The line dash to use, by default "solid" (uses the trace line dash if trace is specified)
        legendrank : `int`, optional
            The legend rank, by default None (e.g. 1 is above 2)

        Raises
        ------
        ValueError
            If trace is not found
        ValueError
            If label is not specified and trace is not specified
        """
        if trace:
            for trace_ in self.data:
                if trace_.name == trace:
                    for arg, default in zip(
                        [label, mode, marker, line_dash],
                        [trace, trace_.mode, trace_.marker, trace_.line_dash],
                    ):
                        if (
                            not arg and default
                        ):  # pragma: no cover - dead: trace_.line_dash raises AttributeError above
                            arg = default  # noqa: PLW2901

                    kwargs.update(
                        dict(yaxis=trace_.yaxis)
                    )  # pragma: no cover - dead: trace_.line_dash raises AttributeError above
                    break  # pragma: no cover - dead: trace_.line_dash raises AttributeError above
            else:
                raise ValueError(f"Trace '{trace}' not found")

        if not label:
            raise ValueError("Label must be specified")

        self.add_scatter(
            x=[None],
            y=[None],
            mode=mode or "lines",
            name=label,
            marker=marker or dict(),
            line_dash=line_dash or "solid",
            legendrank=legendrank,
            **kwargs,
        )

    def show(  # noqa: PLR0915
        self,
        *args,
        external: bool = False,
        export_image: Path | str | None = "",
        **kwargs,
    ) -> "OpenBBFigure":
        """Show the figure.

        Parameters
        ----------
        external : `bool`, optional
            Whether to return the figure object instead of showing it, by default False
        export_image : `Union[Path, str]`, optional
            The path to export the figure image to, by default ""
        cmd_xshift : `int`, optional
            The x shift of the command source annotation, by default 0
        bar_width : `float`, optional
            The width of the bars, by default 0.0001
        date_xaxis : `bool`, optional
            Whether to check if the xaxis is a date axis, by default True
        """
        self.cmd_xshift = kwargs.pop("cmd_xshift", self.cmd_xshift)
        self.bar_width = kwargs.pop("bar_width", self.bar_width)

        if kwargs.pop("margin", True):
            self._adjust_margins()

        self._apply_feature_flags()
        if kwargs.pop("date_xaxis", True):
            self.add_rangebreaks()
            self._xaxis_tickformatstops()

        self.update_traces(marker_line_width=self.bar_width, selector=dict(type="bar"))
        self.update_traces(
            selector=dict(type="scatter", hovertemplate=None),
            hovertemplate="%{y}",
        )

        self.update_layout(
            newshape_line_color=(
                "gold" if self._theme.mapbox_style == "dark" else "#0d0887"
            ),
            modebar=dict(orientation="v"),
            spikedistance=2,
            hoverdistance=2,
        )

        if external:
            return self

        if getattr(self._charting_settings, "headless", False):
            return self.to_json()

        command_location = kwargs.pop("command_location", "")
        try:
            if self._backend is not None:
                return self._backend.send_figure(
                    fig=self, command_location=command_location
                )
        except Exception as e:
            warn(f"Failed to show figure with backend. {e}")

        return pio.show(self, *args, **kwargs)

    def _xaxis_tickformatstops(self) -> None:
        """Set the datetickformatstops for the xaxis if the x data is datetime."""
        if (dateindex := self.get_dateindex()) is None or list(
            self.select_xaxes(lambda x: hasattr(x, "tickformat") and x.tickformat)
        ):
            return

        tickformatstops = [
            dict(dtickrange=[None, 86_400_000], value="%I:%M%p\n%b,%d"),
            dict(dtickrange=[86_400_000, 604_800_000], value="%Y-%m-%d"),
        ]
        xhoverformat = "%I:%M%p %Y-%m-%d"

        if (
            not hasattr(dateindex[-1], "time")
            or dateindex[-1].time() == dateindex[-2].time()
        ):
            xhoverformat = "%Y-%m-%d"
            tickformatstops = [dict(dtickrange=[None, 604_800_000], value="%Y-%m-%d")]

        for entry in self._date_xaxs.values():
            self.update_xaxes(
                tickformatstops=[
                    *tickformatstops,
                    dict(dtickrange=[604_800_000, "M1"], value="%Y-%m-%d"),
                    dict(dtickrange=["M1", None], value="%Y-%m-%d"),
                ],
                type="date",
                row=entry["row"],
                col=entry["col"],
                tick0=0.5,
            )
            self.update_traces(
                xhoverformat=xhoverformat, selector=dict(name=entry["name"])
            )

    def get_subplots_dict(self) -> dict[str, dict[str, list[Any]]]:
        """Return the subplots dict.

        Returns
        -------
        `dict`
            The subplots dict
        """
        subplots: dict[str, dict[str, list[Any]]] = {}

        if not self.has_subplots:
            return subplots

        grid_ref = self._validate_get_grid_ref()
        for r, plot_row in enumerate(grid_ref):
            for c, plot_refs in enumerate(plot_row):
                if not plot_refs:
                    continue
                for subplot_ref in plot_refs:
                    if subplot_ref.subplot_type == "xy":
                        xaxis, yaxis = subplot_ref.layout_keys
                        xref = xaxis.replace("axis", "")
                        yref = yaxis.replace("axis", "")
                        row = r + 1
                        col = c + 1
                        subplots.setdefault(xref, {}).setdefault(yref, []).append(
                            (row, col)
                        )

        return subplots

    def get_dateindex(self) -> list[datetime] | None:
        """Return the dateindex of the figure.

        Returns
        -------
        `list`
            The dateindex
        """
        from numpy import datetime64
        from pandas import DatetimeIndex, to_datetime

        output: list[datetime] | None = None
        subplots = self.get_subplots_dict()

        try:
            false_y = list(self.select_traces(secondary_y=False))
            true_y = list(self.select_traces(secondary_y=True))
        except Exception:
            false_y = []
            true_y = []

        for trace in self.select_traces():
            if not hasattr(trace, "xaxis"):
                continue
            xref, yref = trace.xaxis, trace.yaxis
            row, col = subplots.get(xref, {}).get(yref, [(None, None)])[0]

            if trace.x is not None and len(trace.x) > 5:
                for x in trace.x[:2]:
                    if isinstance(x, (datetime, datetime64, DatetimeIndex)):
                        output = trace.x
                        name = trace.name if hasattr(trace, "name") else f"{trace}"

                        secondary_y: bool | None = trace in true_y
                        if trace not in (false_y + true_y):
                            secondary_y = None

                        self._date_xaxs[trace.xaxis] = {
                            "yaxis": trace.yaxis,
                            "name": name,
                            "row": row,
                            "col": col,
                            "secondary_y": secondary_y,
                        }
                        self._subplot_xdates.setdefault(row, {}).setdefault(
                            col, []
                        ).append(trace.x)

        if output is not None and isinstance(output[0], datetime64):
            output = (
                to_datetime(output).to_pydatetime().astype("datetime64[ms]").tolist()
            )

        return output

    def hide_date_gaps(
        self,
        df_data: "DataFrame",
        row: int | None = None,
        col: int | None = None,
    ) -> None:
        """Add rangebreaks to hide datetime gaps on the xaxis.

        Parameters
        ----------
        df_data : `DataFrame`
            The dataframe with the data.
        row : `int`, optional
            The row of the subplot to hide the gaps, by default None
        col : `int`, optional
            The column of the subplot to hide the gaps, by default None
        """
        from pandas import date_range, to_datetime

        dt_start, dt_end = df_data.index.min(), df_data.index.max()
        rangebreaks: list[dict[str, Any]] = []

        check_freq = df_data.index.to_series().diff(-5).dt.days.abs().mode().iloc[0]
        if check_freq > 7:
            return

        is_daily = df_data.index[-1].time() == df_data.index[-2].time()
        dt_days = date_range(start=dt_start, end=dt_end, normalize=True)

        dt_missing_days = list(
            set(dt_days.strftime("%Y-%m-%d")) - set(df_data.index.strftime("%Y-%m-%d"))  # ty: ignore[unresolved-attribute]
        )
        dt_missing_days = to_datetime(dt_missing_days)

        if len(dt_missing_days) < 2_000:
            rangebreaks = [dict(values=dt_missing_days)]

        df_data = df_data.sort_index()
        if not is_daily:
            for i in range(len(df_data) - 1):
                if df_data.index[i + 1] - df_data.index[i] > timedelta(hours=2):
                    rangebreaks.insert(
                        0,
                        dict(
                            bounds=[
                                df_data.index[i]
                                + timedelta(minutes=60 - df_data.index[i].minute),
                                df_data.index[i + 1],
                            ]
                        ),
                    )

        self.update_xaxes(rangebreaks=rangebreaks, row=row, col=col)

    def add_rangebreaks(self) -> None:
        """Add rangebreaks to hide datetime gaps on the xaxis."""
        from numpy import concatenate
        from pandas import DataFrame, to_datetime

        if self.get_dateindex() is None:
            return

        for row, row_dict in self._subplot_xdates.items():
            for col, values in row_dict.items():
                try:
                    x_values = to_datetime(concatenate(values)).to_pydatetime()  # ty: ignore[unresolved-attribute]
                    self.hide_date_gaps(
                        DataFrame(index=x_values.tolist()),
                        row=row,
                        col=col,
                    )
                except ValueError:
                    continue

    def to_subplot(
        self,
        subplot: "OpenBBFigure",
        row: int,
        col: int,
        secondary_y: bool = False,
        **kwargs,
    ) -> "OpenBBFigure":
        """Return the figure as a subplot of another figure.

        Parameters
        ----------
        subplot : `plotly.graph_objects.Figure`
            Figure object created with `OpenBBFigure.create_subplots` / `plotly.subplots.make_subplots`
        row : `int`
            Row number
        col : `int`
            Column number
        secondary_y : `bool`, optional
            Whether to use the secondary y axis, by default False

        Returns
        -------
        `plotly.graph_objects.Figure`
            The subplot with the figure added
        """
        for trace in self.data:
            if kwargs:
                trace.update(**kwargs)

            subplot.add_trace(trace, row=row, col=col, secondary_y=secondary_y)
            subplot.set_xaxis_title(self.layout.xaxis.title.text, row=row, col=col)
            subplot.set_yaxis_title(self.layout.yaxis.title.text, row=row, col=col)

        return subplot

    def to_html(self, *args, **kwargs) -> str:
        """Return the figure as HTML."""
        self.update_traces(marker_line_width=0.0001, selector=dict(type="bar"))
        kwargs.update(
            dict(
                config={
                    "displayModeBar": False,
                    "edits": {
                        "colorbarPosition": True,
                        "legendPosition": True,
                    },
                    "scrollZoom": True,
                },
                include_plotlyjs=kwargs.pop("include_plotlyjs", False),
                full_html=False,
            )
        )
        self._apply_feature_flags()
        self._xaxis_tickformatstops()

        return super().to_html(*args, **kwargs)

    def to_plotly_json(self) -> dict:
        """Serialize, then deserialize, the figure to JSON. Returns as a Python dictionary."""

        if "t" in self.layout.margin and (
            self.layout.margin["t"] is None or (self.layout.margin["t"] < 50)
        ):
            self.layout.margin["t"] = 50

        fig = super().to_json() or "{}"
        fig = json.loads(fig)

        fig.update(
            {
                "config": {
                    "displayModeBar": False,
                    "edits": {
                        "colorbarPosition": True,
                        "legendPosition": True,
                    },
                    "scrollZoom": True,
                }
            }
        )

        return fig

    @staticmethod
    def row_colors(data: "DataFrame") -> list[str] | None:
        """Return the row colors of the table.

        Parameters
        ----------
        data : `DataFrame`
            The dataframe

        Returns
        -------
        `list`
            The list of colors
        """
        row_count = len(data)
        row_odd_count = floor(row_count / 2) + row_count % 2
        row_even_count = floor(row_count / 2)
        odd_list = [PLT_TBL_ROW_COLORS[0]] * row_odd_count
        even_list = [PLT_TBL_ROW_COLORS[1]] * row_even_count
        color_list = [x for y in zip(odd_list, even_list) for x in y]
        if row_odd_count > row_even_count:
            color_list.append(PLT_TBL_ROW_COLORS[0])

        return color_list

    @staticmethod
    def _tbl_values(data: "DataFrame", print_index: bool) -> tuple[list[str], list]:
        """Return the values of the table.

        Parameters
        ----------
        data : `DataFrame`
            The dataframe to convert
        print_index : `bool`
            Whether to print the index

        Returns
        -------
        `tuple`
            The header values and the cell values
        """
        if print_index:
            header_values = list(
                [data.index.name if data.index.name is not None else "", *data.columns]
            )
            cell_values = [data.index, *[data[col] for col in data]]

        else:
            header_values = data.columns.to_list()
            cell_values = [data[col] for col in data]

        header_values = [f"<b>{x}</b>" for x in header_values]

        return header_values, cell_values

    @classmethod
    def to_table(
        cls,
        data: "DataFrame",
        columnwidth: list[int | float] | None = None,
        print_index: bool = True,
        **kwargs,
    ) -> "OpenBBFigure":
        """Convert a dataframe to a table figure.

        Parameters
        ----------
        data : `DataFrame`
            The dataframe to convert
        columnwidth : `list`, optional
            The width of each column, by default None (auto)
        print_index : `bool`, optional
            Whether to print the index, by default True
        height : `int`, optional
            The height of the table, by default len(data.index) * 28 + 25
        width : `int`, optional
            The width of the table, by default sum(columnwidth) * 8.7

        Returns
        -------
        `plotly.graph_objects.Figure`
            The figure as a table
        """
        if not columnwidth:
            columnwidth = [
                max(len(str(data[col].name)), data[col].astype(str).str.len().max())
                for col in data.columns
            ]
            if print_index:
                columnwidth.insert(
                    0,
                    max(
                        len(str(data.index.name)),
                        data.index.astype(str).str.len().max(),
                    ),
                )

            columnwidth = [
                int(x + (max(columnwidth) - min(columnwidth)) * 0.2)
                for x in columnwidth
            ]

        header_values, cell_values = cls._tbl_values(data, print_index)

        if (height := kwargs.get("height")) and height < len(data.index) * 28 + 25:
            kwargs.pop("height")
        if (width := kwargs.get("width")) and width < sum(columnwidth) * 8.7:
            kwargs.pop("width")

        height = kwargs.pop("height", len(data.index) * 28 + 25)
        width = kwargs.pop("width", sum(columnwidth) * 8.7)

        fig = OpenBBFigure()
        fig.add_table(
            header=dict(values=header_values),
            cells=dict(
                values=cell_values,
                align="left",
                height=25,
            ),
            columnwidth=columnwidth,
            **kwargs,
        )
        fig.update_layout(
            height=height,
            width=width,
            template="openbb_tables",
            margin=dict(l=0, r=0, b=0, t=0, pad=0),
            font=dict(size=14),
        )

        return fig

    def _adjust_margins(self) -> None:
        """Adjust the margins of the figure."""
        if self._margin_adjusted:
            return

        margin_add = (
            dict(l=80, r=60, b=30, t=40, pad=0)
            if not self._has_secondary_y or not self.has_subplots
            else dict(l=60, r=50, b=35, t=40, pad=0)
        )

        for key in ["l", "r", "b", "t", "pad"]:
            if key in self.layout.margin and self.layout.margin[key] is not None:
                self.layout.margin[key] += margin_add.get(key, 0)
            else:
                self.layout.margin[key] = margin_add.get(key, 0)

        self._margin_adjusted = True

    def _add_cmd_source(self, command_location: str | None = "") -> None:
        """Set the watermark for OpenBB Terminal."""
        if command_location:
            yaxis = self.layout.yaxis
            yaxis2 = self.layout.yaxis2 if hasattr(self.layout, "yaxis2") else None
            xshift = -70 if yaxis.side == "right" else -80

            if self.layout.margin["l"] > 100:
                xshift -= 50 if self._added_logscale else 40

            if (
                yaxis2
                and (yaxis.title.text and yaxis2.title.text)
                and (yaxis.side == "left" or yaxis2.side == "left")
            ):
                self.layout.margin["l"] += 20

            if (yaxis2 and yaxis2.side == "left") or yaxis.side == "left":
                title = (
                    yaxis.title.text
                    if not yaxis2 or yaxis2.side != "left"
                    else yaxis2.title.text
                )
                xshift = -110 if not title else -135
                self.layout.margin["l"] += 60

            self.add_annotation(
                x=0,
                y=0.5,
                yref="paper",
                xref="paper",
                text=command_location,
                textangle=-90,
                font_size=24,
                font_color="gray" if self._theme.mapbox_style == "dark" else "black",
                opacity=0.5,
                yanchor="middle",
                xanchor="left",
                xshift=xshift + self.cmd_xshift,
            )

    def _apply_feature_flags(self) -> None:
        """Apply watermark and command source annotations."""
        if self._feature_flags_applied:
            return

        self._add_cmd_source()

        self._feature_flags_applied = True

    def add_logscale_menus(self, yaxis: str = "yaxis") -> None:
        """Set the menus for the figure."""
        self._added_logscale = True
        bg_color = "#000000" if self._theme.mapbox_style == "dark" else "#FFFFFF"
        font_color = "#FFFFFF" if self._theme.mapbox_style == "dark" else "#000000"
        self.update_layout(
            xaxis=dict(
                rangeslider=dict(visible=False),
                rangeselector=dict(
                    bgcolor=bg_color,
                    font=dict(color=font_color),
                    buttons=list(
                        [
                            dict(
                                count=1,
                                label="1M",
                                step="month",
                                stepmode="backward",
                            ),
                            dict(
                                count=3,
                                label="3M",
                                step="month",
                                stepmode="backward",
                            ),
                            dict(count=1, label="YTD", step="year", stepmode="todate"),
                            dict(
                                count=1,
                                label="1y",
                                step="year",
                                stepmode="backward",
                            ),
                            dict(step="all"),
                        ]
                    ),
                ),
            ),
            bargap=0,
            bargroupgap=0,
        )

        self.update_layout(
            updatemenus=[
                dict(
                    bgcolor=bg_color,
                    font=dict(color=font_color, size=14),
                    buttons=[
                        dict(
                            label="linear   ",
                            method="relayout",
                            args=[{f"{yaxis}.type": "linear"}],
                        ),
                        dict(
                            label="log",
                            method="relayout",
                            args=[{f"{yaxis}.type": "log"}],
                        ),
                    ],
                    y=1.07,
                    x=-0.01,
                )
            ],
        )

    def add_corr_plot(
        self,
        series: "DataFrame",
        max_lag: int = 20,
        m: int | None = None,
        alpha: float | None = 0.05,
        marker: dict | None = None,
        row: int | None = None,
        col: int | None = None,
        pacf: bool = False,
        **kwargs,
    ) -> None:
        """Add a correlation plot to a figure object.

        Parameters
        ----------
        fig : OpenBBFigure
            Figure object to add plot to
        series : DataFrame
            Dataframe to look at
        max_lag : int, optional
            Number of lags to look at, by default 15
        m: Optional[int]
            Optionally, a time lag to highlight on the plot. Default is none.
        alpha: Optional[float]
            Optionally, a significance level to highlight on the plot. Default is 0.05.
        row : int, optional
            Row to add plot to, by default None
        col : int, optional
            Column to add plot to, by default None
        pacf : bool, optional
            Flag to indicate whether to use partial autocorrelation or not, by default False
        """
        import statsmodels.api as sm  # noqa
        from numpy import arange, asanyarray, ceil, log10, isscalar  # noqa

        mode = "markers+lines" if marker else "lines"
        line = kwargs.pop("line", None)

        def _prepare_data_corr_plot(x, lags):
            zero = True
            irregular = False
            if lags is None:
                nobs = x.shape[0]
                lim = min(int(ceil(10 * log10(nobs))), nobs - 1)
                lags = arange(not zero, lim + 1)
            elif isscalar(lags):
                lags = arange(
                    not zero,
                    int(lags) + 1,  # ty: ignore[invalid-argument-type]
                )
            else:
                irregular = True
                lags = asanyarray(lags).astype(int)
            nlags = lags.max(0)

            return lags, nlags, irregular

        lags, nlags, irregular = _prepare_data_corr_plot(series, max_lag)

        callback = sm.tsa.stattools.pacf if pacf else sm.tsa.stattools.acf
        if not pacf:
            kwargs.update(dict(fft=False))

        acf_x = callback(
            series,  # ty: ignore[invalid-argument-type]
            nlags=nlags,
            alpha=alpha,
            result_object=True,
            **kwargs,
        )

        acf_x, confint = acf_x[:2] if not pacf else acf_x

        if confint is None:
            raise ValueError("`alpha` is required to plot the confidence band.")

        if irregular:
            acf_x = acf_x[lags]

        try:
            confint = confint[lags]
            if lags[0] == 0:
                lags = lags[1:]
                confint = confint[1:]
                acf_x = acf_x[1:]
            lags = lags.astype(float)
            lags[0] -= 0.5
            lags[-1] += 0.5

            upp_band = confint[:, 0] - acf_x
            low_band = confint[:, 1] - acf_x

            for x in range(len(acf_x)):
                self.add_scatter(
                    x=(x, x),
                    y=(0, acf_x[x]),
                    mode=mode,
                    marker=marker,
                    line=line,
                    line_width=(2 if m is not None and x == m else 1),
                    row=row,
                    col=col,
                )

            self.add_scatter(
                x=lags,
                y=upp_band,
                mode="lines",
                line_color="rgba(0, 0, 0, 0)",
                opacity=0,
                row=row,
                col=col,
            )

            self.add_scatter(
                x=lags,
                y=low_band,
                mode="lines",
                fillcolor="rgba(255, 217, 0, 0.30)",
                fill="tonexty",
                line_color="rgba(0, 0, 0, 0.0)",
                opacity=0,
                row=row,
                col=col,
            )
            self.add_scatter(
                x=[0, max_lag + 1],
                y=[0, 0],
                mode="lines",
                line_color="white",
                row=row,
                col=col,
            )
            self.update_traces(showlegend=False)

        except ValueError:  # pragma: no cover
            pass

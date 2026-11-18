"""Chart and style helpers for Plotly."""

import json
import sys
from pathlib import Path
from typing import (
    Any,
    ClassVar,
)
from warnings import warn

import plotly.graph_objects as go
import plotly.io as pio

from openbb_charting.core.config.openbb_styles import (
    PLT_COLORWAY,
    PLT_DECREASING_COLORWAY,
    PLT_INCREASING_COLORWAY,
)


def map_layout_key() -> str:
    """Return the layout key this Plotly uses for map styling.

    Plotly 7 removed ``layout.mapbox`` in favour of ``layout.map``.
    """
    valid = getattr(go.Layout, "_valid_props", None)

    if not valid or "mapbox" in valid:
        return "mapbox"

    return "map"


def prune_unsupported_layout(template: dict) -> dict:
    """Drop the layout keys the installed Plotly rejects, in place.


    Parameters
    ----------
    template : dict
        A Plotly template dict; its ``layout`` is filtered in place.

    Returns
    -------
    dict
        The same template, with unsupported layout keys removed.
    """
    layout = template.get("layout")
    valid = getattr(go.Layout, "_valid_props", None)

    if not valid or not isinstance(layout, dict):
        return template

    for key in [k for k in layout if k not in valid]:
        layout.pop(key)

    return template


class ChartStyle:
    """The class that helps with handling of style configurations."""

    STYLES_REPO = Path(__file__).parent.parent / "styles"
    user_styles_directory: Path = STYLES_REPO

    plt_styles_available: dict[str, Path] = {}
    plt_style: str = "dark"
    plotly_template: dict[str, Any] = {}
    mapbox_style: str = "dark"

    line_color: str = ""
    up_color: str = ""
    down_color: str = ""
    up_colorway: list[str] = []
    down_colorway: list[str] = []
    up_color_transparent: str = ""
    down_color_transparent: str = ""

    line_width: float = 1.5

    initialized: bool = False
    instance: ClassVar["ChartStyle | None"] = None

    def __new__(cls, *args, **kwargs):
        """Create a singleton."""
        if cls.instance is None:
            cls.instance = super().__new__(cls)
        return cls.instance

    def __init__(
        self,
        plt_style: str | None = "",
        user_styles_directory: Path | None = None,
    ):
        """Initialize the class.

        Parameters
        ----------
        plt_style : `str`, optional
            The name of the Plotly style to use, by default ""
        """
        from openbb_core.app.service.user_service import UserService

        if self.initialized:
            return

        user_settings = UserService().read_from_file()
        pref_style = getattr(user_settings.preferences, "chart_style", None)
        plt_style = plt_style or pref_style

        self.initialized = True
        self.user_styles_directory = user_styles_directory or self.user_styles_directory
        self.plt_style = plt_style or self.plt_style
        self.load_available_styles()
        self.load_style(plt_style)
        self.apply_style()

    def apply_style(self, style: str | None = "") -> None:
        """Apply the style to the libraries."""
        style = style or self.plt_style

        if style != self.plt_style:
            self.load_style(style)

        style = style.lower().replace("light", "white")

        if self.plt_style and self.plotly_template:
            map_key = map_layout_key()
            prune_unsupported_layout(self.plotly_template)
            self.plotly_template.setdefault("layout", {}).setdefault(
                map_key, {}
            ).setdefault("style", "dark")
            if "tables" in self.plt_styles_available:
                tables = self.load_json_style(self.plt_styles_available["tables"])
                pio.templates["openbb_tables"] = go.layout.Template(
                    prune_unsupported_layout(tables)
                )
            try:
                pio.templates["openbb"] = go.layout.Template(self.plotly_template)
            except ValueError as err:
                if (
                    "plotly.graph_objs.Layout: 'legend2'" in str(err)
                ):  # pragma: no cover - plotly<5.15 only; installed plotly supports legend2
                    warn(
                        "[red]Warning: Plotly multiple legends are "
                        "not supported in currently installed version.[/]\n\n"
                        "[yellow]Please update plotly to version >= 5.15.0[/]\n"
                        "[green]pip install plotly --upgrade[/]"
                    )
                    sys.exit(1)

            if style in ["dark", "white"]:
                pio.templates.default = f"plotly_{style}+openbb"
                return

            pio.templates.default = "openbb"
            self.mapbox_style = (
                self.plotly_template.setdefault("layout", {})
                .setdefault(map_key, {})
                .setdefault("style", "dark")
            )

    def load_available_styles_from_folder(self, folder: Path | str) -> None:
        """Load custom styles from folder.

        Parameters
        ----------
        folder : str
            Path to the folder containing the stylesheets
        """

        if not isinstance(folder, Path) or not folder.exists():
            return

        for attr, ext in zip(
            ["plt_styles_available", "console_styles_available"],
            [".pltstyle.json", ".richstyle.json"],
        ):
            for file in folder.rglob(f"*{ext}"):
                getattr(self, attr)[file.name.replace(ext, "")] = file

    def load_available_styles(self) -> None:
        """Load custom styles from default and user folders."""
        self.load_available_styles_from_folder(self.STYLES_REPO)
        self.load_available_styles_from_folder(self.user_styles_directory)

    def load_json_style(self, file: Path) -> dict[str, Any]:
        """Load style from json file.

        Parameters
        ----------
        file : Path
            Path to the file containing the style

        Returns
        -------
        Dict[str, Any]
            Style as a dictionary
        """
        with open(file) as f:
            return json.load(f)

    def load_style(self, style: str | None = "") -> None:
        """Load style from file.

        Parameters
        ----------
        style : str
            Name of the style to load
        """
        style = style or self.plt_style

        if style not in self.plt_styles_available:
            warn(
                f"[red]Plot Style {style} not found. Using default style.[/red]",
            )
            style = "dark"

        self.load_plt_style(style)

    def load_plt_style(self, style: str) -> None:
        """Load Plotly style from file.

        Parameters
        ----------
        style : str
            Name of the style to load
        """
        self.plt_style = style
        self.plotly_template = self.load_json_style(self.plt_styles_available[style])
        line = self.plotly_template.pop("line", {})

        self.up_color = line.get("up_color", "#00ACFF")
        self.down_color = line.get("down_color", "#FF0000")
        self.up_color_transparent = line.get(
            "up_color_transparent", "rgba(0, 170, 255, 0.50)"
        )
        self.down_color_transparent = line.get(
            "down_color_transparent", "rgba(230, 0, 57, 0.50)"
        )
        self.line_color = line.get("color", "#ffed00")
        self.line_width = line.get("width", self.line_width)
        self.down_colorway = line.get("down_colorway", PLT_DECREASING_COLORWAY)
        self.up_colorway = line.get("up_colorway", PLT_INCREASING_COLORWAY)

    def get_colors(self, reverse: bool = False) -> list:
        """Get colors for the plot.

        Parameters
        ----------
        reverse : bool, optional
            Whether to reverse the colors, by default False

        Returns
        -------
        list
            List of colors e.g. ["#00ACFF", "#FF0000"]
        """
        colors = (
            self.plotly_template.get("layout", {}).get("colorway", PLT_COLORWAY).copy()
        )
        if reverse:
            colors.reverse()
        return colors

"""Technical Analysis Helpers."""

from typing import TYPE_CHECKING, Any, Literal
from warnings import warn

if TYPE_CHECKING:
    from pandas import DataFrame, Series, Timestamp


def validate_data(data: list, length: int | list[int]) -> None:
    """Validate data."""
    if isinstance(length, int):
        length = [length]
    for item in length:
        if item > len(data):
            raise ValueError(
                f"Data length is less than required by parameters: {max(length)}"
            )


def parkinson(
    data: "DataFrame",
    window: int = 30,
    trading_periods: int | None = None,
    is_crypto: bool = False,
    clean=True,
) -> "DataFrame":
    """Parkinson volatility.

    Uses the high and low price of the day rather than just close to close prices.
    It is useful for capturing large price movements during the day.

    Parameters
    ----------
    data : DataFrame
        Dataframe of OHLC prices.
    window : int [default: 30]
        Length of window to calculate over.
    trading_periods : Optional[int] [default: 252]
        Number of trading periods in a year.
    is_crypto : bool [default: False]
        If true, trading_periods is defined as 365.
    clean : bool [default: True]
        Whether to clean the data or not by dropping NaN values.

    Returns
    -------
    DataFrame : results
        Dataframe with results.
    """
    from numpy import log

    if window < 1:
        warn("Error: Window must be at least 1, defaulting to 30.")
        window = 30

    if trading_periods and is_crypto:
        warn("is_crypto is overridden by trading_periods.")

    if not trading_periods:
        trading_periods = 365 if is_crypto else 252

    rs = (1.0 / (4.0 * log(2.0))) * ((data["high"] / data["low"]).apply(log)) ** 2.0

    def f(v):
        return (trading_periods * v.mean()) ** 0.5

    result = rs.rolling(window=window, center=False).apply(func=f)

    if clean:
        return result.dropna()

    return result


def standard_deviation(
    data: "DataFrame",
    window: int = 30,
    trading_periods: int | None = None,
    is_crypto: bool = False,
    clean: bool = True,
) -> "DataFrame":
    """Calculate the Standard deviation.

    Measures how widely returns are dispersed from the average return.
    It is the most common (and biased) estimator of volatility.

    Parameters
    ----------
    data : DataFrame
        Dataframe of OHLC prices.
    window : int [default: 30]
        Length of window to calculate over.
    trading_periods : Optional[int] [default: 252]
        Number of trading periods in a year.
    is_crypto : bool [default: False]
        If true, trading_periods is defined as 365.
    clean : bool [default: True]
        Whether to clean the data or not by dropping NaN values.

    Returns
    -------
    DataFrame : results
        Dataframe with results.
    """
    from numpy import log, sqrt

    if window < 2:
        warn("Error: Window must be at least 2, defaulting to 30.")
        window = 30

    if trading_periods and is_crypto:
        warn("is_crypto is overridden by trading_periods.")

    if not trading_periods:
        trading_periods = 365 if is_crypto else 252

    log_return = (data["close"] / data["close"].shift(1)).apply(log)

    result = log_return.rolling(window=window, center=False).std() * sqrt(
        trading_periods
    )

    if clean:
        return result.dropna()

    return result


def garman_klass(
    data: "DataFrame",
    window: int = 30,
    trading_periods: int | None = None,
    is_crypto: bool = False,
    clean=True,
) -> "DataFrame":
    """Garman-Klass volatility.

    Extends Parkinson volatility by taking into account the opening and closing price.
    As markets are most active during the opening and closing of a trading session.
    It makes volatility estimation more accurate.

    Parameters
    ----------
    data : DataFrame
        Dataframe of OHLC prices.
    window : int [default: 30]
        Length of window to calculate over.
    trading_periods : Optional[int] [default: 252]
        Number of trading periods in a year.
    is_crypto : bool [default: False]
        If true, trading_periods is defined as 365.
    clean : bool [default: True]
        Whether to clean the data or not by dropping NaN values.

    Returns
    -------
    DataFrame : results
        Dataframe with results.
    """
    from numpy import log

    if window < 1:
        warn("Error: Window must be at least 1, defaulting to 30.")
        window = 30

    if trading_periods and is_crypto:
        warn("is_crypto is overridden by trading_periods.")

    if not trading_periods:
        trading_periods = 365 if is_crypto else 252

    log_hl = (data["high"] / data["low"]).apply(log)
    log_co = (data["close"] / data["open"]).apply(log)

    rs = 0.5 * log_hl**2 - (2 * log(2) - 1) * log_co**2

    def f(v):
        return (trading_periods * v.mean()) ** 0.5

    result = rs.rolling(window=window, center=False).apply(func=f)

    if clean:
        return result.dropna()

    return result


def hodges_tompkins(
    data: "DataFrame",
    window: int = 30,
    trading_periods: int | None = None,
    is_crypto: bool = False,
    clean=True,
) -> "DataFrame":
    """Hodges-Tompkins volatility.

    Is a bias correction for estimation using an overlapping data sample.
    It produces unbiased estimates and a substantial gain in efficiency.

    Parameters
    ----------
    data : DataFrame
        Dataframe of OHLC prices.
    window : int [default: 30]
        Length of window to calculate over.
    trading_periods : Optional[int] [default: 252]
        Number of trading periods in a year.
    is_crypto : bool [default: False]
        If true, trading_periods is defined as 365.
    clean : bool [default: True]
        Whether to clean the data or not by dropping NaN values.

    Returns
    -------
    DataFrame : results
        Dataframe with results.

    Example
    -------
    >>> data = obb.equity.price.historical('BTC-USD')
    >>> df = obb.technical.hodges_tompkins(data, is_crypto = True)
    """
    from numpy import log, sqrt

    if window < 2:
        warn("Error: Window must be at least 2, defaulting to 30.")
        window = 30

    if trading_periods and is_crypto:
        warn("is_crypto is overridden by trading_periods.")

    if not trading_periods:
        trading_periods = 365 if is_crypto else 252

    log_return = (data["close"] / data["close"].shift(1)).apply(log)

    vol = log_return.rolling(window=window, center=False).std() * sqrt(trading_periods)

    h = window
    n = (log_return.count() - h) + 1

    adj_factor = 1.0 / (1.0 - (h / n) + ((h**2 - 1) / (3 * n**2)))

    result = vol * adj_factor

    if clean:
        return result.dropna()

    return result


def rogers_satchell(
    data: "DataFrame",
    window: int = 30,
    trading_periods: int | None = None,
    is_crypto: bool = False,
    clean=True,
) -> "Series":
    """Rogers-Satchell Estimator.

    Is an estimator for measuring the volatility with an average return not equal to zero.
    Unlike Parkinson and Garman-Klass estimators, Rogers-Satchell incorporates a drift term,
    mean return not equal to zero.

    Parameters
    ----------
    data : DataFrame
        Dataframe of OHLC prices.
    window : int [default: 30]
        Length of window to calculate over.
    trading_periods : Optional[int] [default: 252]
        Number of trading periods in a year.
    is_crypto : bool [default: False]
        If true, trading_periods is defined as 365.
    clean : bool [default: True]
        Whether to clean the data or not by dropping NaN values.

    Returns
    -------
    Series : results
        Pandas Series with results.
    """
    from numpy import log

    if window < 1:
        warn("Error: Window must be at least 1, defaulting to 30.")
        window = 30

    if trading_periods and is_crypto:
        warn("is_crypto is overridden by trading_periods.")

    if not trading_periods:
        trading_periods = 365 if is_crypto else 252

    log_ho = (data["high"] / data["open"]).apply(log)
    log_lo = (data["low"] / data["open"]).apply(log)
    log_co = (data["close"] / data["open"]).apply(log)

    rs = log_ho * (log_ho - log_co) + log_lo * (log_lo - log_co)

    def f(v):
        return (trading_periods * v.mean()) ** 0.5

    result = rs.rolling(window=window, center=False).apply(func=f)

    if clean:
        return result.dropna()

    return result


def yang_zhang(
    data: "DataFrame",
    window: int = 30,
    trading_periods: int | None = None,
    is_crypto: bool = False,
    clean=True,
) -> "DataFrame":
    """Yang-Zhang Volatility.

    Is the combination of the overnight (close-to-open volatility).
    It is a weighted average of the Rogers-Satchell volatility and the open-to-close volatility.

    Parameters
    ----------
    data : DataFrame
        Dataframe of OHLC prices.
    window : int [default: 30]
        Length of window to calculate standard deviation.
    trading_periods : Optional[int] [default: 252]
        Number of trading periods in a year.
    is_crypto : bool [default: False]
        If true, trading_periods is defined as 365.
    clean : bool [default: True]
        Whether to clean the data or not by dropping NaN values.

    Returns
    -------
    DataFrame : results
        Dataframe with results.
    """
    from numpy import log, sqrt

    if window < 2:
        warn("Error: Window must be at least 2, defaulting to 30.")
        window = 30

    if trading_periods and is_crypto:
        warn("is_crypto is overridden by trading_periods.")

    if not trading_periods:
        trading_periods = 365 if is_crypto else 252

    log_ho = (data["high"] / data["open"]).apply(log)
    log_lo = (data["low"] / data["open"]).apply(log)
    log_co = (data["close"] / data["open"]).apply(log)

    log_oc = (data["open"] / data["close"].shift(1)).apply(log)
    log_oc_sq = log_oc**2

    log_cc = (data["close"] / data["close"].shift(1)).apply(log)
    log_cc_sq = log_cc**2

    rs = log_ho * (log_ho - log_co) + log_lo * (log_lo - log_co)

    close_vol = log_cc_sq.rolling(window=window, center=False).sum() * (
        1.0 / (window - 1.0)
    )
    open_vol = log_oc_sq.rolling(window=window, center=False).sum() * (
        1.0 / (window - 1.0)
    )
    window_rs = rs.rolling(window=window, center=False).sum() * (1.0 / (window - 1.0))

    k = 0.34 / (1.34 + (window + 1) / (window - 1))
    result = (open_vol + k * close_vol + (1 - k) * window_rs).apply(sqrt) * sqrt(
        trading_periods
    )

    if clean:
        return result.dropna()

    return result


def calculate_cones(
    data: "DataFrame",
    lower_q: float,
    upper_q: float,
    is_crypto: bool,
    model: Literal[
        "std",
        "parkinson",
        "garman_klass",
        "hodges_tompkins",
        "rogers_satchell",
        "yang_zhang",
    ],
    trading_periods: int | None = None,
) -> "DataFrame":
    """Calculate Cones."""
    from pandas import DataFrame

    estimator = DataFrame()

    if lower_q > upper_q:
        lower_q, upper_q = upper_q, lower_q

    if (lower_q >= 1) or (upper_q >= 1):
        raise ValueError("Error: lower_q and upper_q must be between 0 and 1")

    lower_q_label = str(int(lower_q * 100))
    upper_q_label = str(int(upper_q * 100))
    quantiles = [lower_q, upper_q]
    windows = [3, 10, 30, 60, 90, 120, 150, 180, 210, 240, 300, 360]
    min_ = []
    max_ = []
    median = []
    top_q = []
    bottom_q = []
    realized = []
    allowed_windows = []
    data = data.sort_index(ascending=True)

    model_functions = {
        "std": standard_deviation,
        "parkinson": parkinson,
        "garman_klass": garman_klass,
        "hodges_tompkins": hodges_tompkins,
        "rogers_satchell": rogers_satchell,
        "yang_zhang": yang_zhang,
    }

    for window in windows:
        estimator = model_functions[model](
            window=window,
            data=data,
            is_crypto=is_crypto,
            trading_periods=trading_periods,
        )

        if estimator.empty:
            continue

        min_.append(estimator.min())
        max_.append(estimator.max())
        median.append(estimator.median())
        top_q.append(estimator.quantile(quantiles[1]))
        bottom_q.append(estimator.quantile(quantiles[0]))
        realized.append(estimator.iloc[-1])

        allowed_windows.append(window)

    df_ = [realized, min_, bottom_q, median, top_q, max_]
    df_windows = allowed_windows
    df = DataFrame(df_, columns=df_windows)
    df = df.rename(
        index={
            0: "realized",
            1: "min",
            2: f"lower_{lower_q_label}%",
            3: "median",
            4: f"upper_{upper_q_label}%",
            5: "max",
        }
    )
    cones_df = df.copy()
    return cones_df.transpose().reset_index().rename(columns={"index": "window"})


def clenow_momentum(
    values: "Series", window: int = 90
) -> tuple[float, float, "Series"]:
    """Clenow Volatility Adjusted Momentum.

    This is defined as the regression coefficient on log prices multiplied by the R^2
    value of the regression.

    Parameters
    ----------
    values: Series
        Values to perform regression for
    window: int
        Length of look back period

    Returns
    -------
    float:
        R2 of fit to log data
    float:
        Coefficient of linear regression
    Series:
        Values for best fit line
    """
    from numpy import arange, exp, log, polyfit
    from pandas import Series

    if len(values) < window:
        raise ValueError(f"Calculation asks for at least last {window} days of data")

    y = log(values[-window:].to_numpy(dtype=float))
    x = arange(len(y))
    coef, intercept = polyfit(x, y, 1)
    fit = coef * x + intercept

    r2 = (
        0.0
        if y.max() == y.min()
        else float(1 - ((y - fit) ** 2).sum() / ((y - y.mean()) ** 2).sum())
    )
    annualized_coef = float(exp(coef) ** 252 - 1)

    return r2, annualized_coef, Series(fit)


def calculate_fib_levels(
    data: "DataFrame",
    close_col: str,
    limit: int = 120,
    start_date: Any | None = None,
    end_date: Any | None = None,
) -> tuple["DataFrame", "Timestamp", "Timestamp", float, float, str]:
    """Calculate Fibonacci levels.

    Parameters
    ----------
    data : DataFrame
        Dataframe of prices
    close_col : str
        Column name of close prices
    limit : int
        Days to look back for retracement
    start_date : Any
        Custom start date for retracement
    end_date : Any
        Custom end date for retracement

    Returns
    -------
    df : DataFrame
        Dataframe of fib levels
    min_date: Timestamp
        Date of min point
    max_date: Timestamp:
        Date of max point
    min_pr: float
        Price at min point
    max_pr: float
        Price at max point
    """
    from pandas import DataFrame

    if close_col not in data.columns:
        raise ValueError(f"Column {close_col} not in data")

    if start_date and end_date:
        if start_date not in data.index:
            date0 = data.index[
                data.index.get_indexer([start_date], method="nearest")[0]
            ]
            warn(f"Start date not in data.  Using nearest: {date0}")
        else:
            date0 = start_date
        if end_date not in data.index:
            date1 = data.index[data.index.get_indexer([end_date], method="nearest")[0]]
            warn(f"End date not in data.  Using nearest: {date1}")
        else:
            date1 = end_date

        data0 = data.loc[date0, close_col]
        data1 = data.loc[date1, close_col]

        min_pr = min(data0, data1)
        max_pr = max(data0, data1)

        if min_pr == data0:
            min_date = date0
            max_date = date1
        else:
            min_date = date1
            max_date = date0
    else:
        data_to_use = data.iloc[-limit:, :][close_col]

        min_pr = data_to_use.min()
        min_date = data_to_use.idxmin()
        max_pr = data_to_use.max()
        max_date = data_to_use.idxmax()

    fib_levels = [0, 0.235, 0.382, 0.5, 0.618, 0.65, 1]

    lvl_text: str = "left" if min_date < max_date else "right"
    if min_date > max_date:
        min_date, max_date = max_date, min_date
        min_pr, max_pr = max_pr, min_pr

    price_dif = max_pr - min_pr

    levels = [
        round(max_pr - price_dif * f_lev, (2 if f_lev > 1 else 4))
        for f_lev in fib_levels
    ]

    df = DataFrame()
    df["Level"] = fib_levels
    df["Level"] = df["Level"].apply(lambda x: str(x * 100) + "%")
    df["Price"] = levels

    return df, min_date, max_date, min_pr, max_pr, lvl_text

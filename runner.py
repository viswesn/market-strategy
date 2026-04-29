"""
Orchestrator — wires together data fetching and strategy execution.
Called by both cli.py and api.py.
"""

from datetime import date, timedelta
from data import fetch_data
from strategies import REGISTRY

YEAR_TO_DAYS = {1: 365, 2: 730, 3: 1095}


def run_backtest(
    symbol: str = "INFY",
    years: int = 1,
    capital: float = 100000,
    strategy: str = "supertrend",
) -> dict:
    """
    Run a strategy backtest.

    Parameters
    ----------
    symbol   : NSE stock symbol (e.g. 'INFY', 'TCS', 'RELIANCE')
    years    : Lookback period — 1, 2, or 3
    capital  : Initial capital in INR
    strategy : Strategy name (must be a key in strategies.REGISTRY)

    Returns
    -------
    dict with keys: symbol, strategy, period, capital, summary, trades, df
    Note: 'df' is a DataFrame — strip it before JSON serialisation.
    """
    strategy = strategy.lower().strip()
    if strategy not in REGISTRY:
        raise ValueError(
            f"Unknown strategy '{strategy}'. Available: {list(REGISTRY.keys())}"
        )

    if years not in YEAR_TO_DAYS:
        raise ValueError(f"Years must be 1, 2, or 3. Got: {years}")

    symbol = symbol.upper().strip()
    end_date = date.today().isoformat()
    start_date = (date.today() - timedelta(days=YEAR_TO_DAYS[years])).isoformat()

    df = fetch_data(symbol=symbol, start_date=start_date, end_date=end_date)

    strategy_fn = REGISTRY[strategy]
    df, summary, trades = strategy_fn(df, capital=capital)

    return {
        "symbol": symbol,
        "strategy": strategy,
        "period": {"start": start_date, "end": end_date},
        "capital": capital,
        "summary": summary,
        "trades": trades,
        "df": df,  # DataFrame — for CLI charting only; excluded from API responses
    }

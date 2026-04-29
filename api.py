"""
FastAPI entry point.

Start the server:
    uvicorn api:app --reload

Endpoints:
    GET /strategies               → list registered strategy names
    GET /backtest?symbol=INFY&years=1&capital=100000&strategy=supertrend
"""

from fastapi import FastAPI, HTTPException, Query
from strategies import REGISTRY
from runner import run_backtest

app = FastAPI(
    title="NSE Strategy Backtester API",
    description="Run strategy backtests on NSE-listed stocks.",
    version="1.0.0",
)


@app.get("/strategies", summary="List available strategies")
def list_strategies():
    """Return the names of all registered strategies."""
    return {"strategies": list(REGISTRY.keys())}


@app.get("/backtest", summary="Run a strategy backtest")
def backtest(
    symbol: str = Query(default="INFY", description="NSE stock symbol, e.g. INFY, TCS"),
    years: int = Query(default=1, ge=1, le=3, description="Lookback period in years (1–3)"),
    capital: float = Query(default=100000, gt=0, description="Initial capital in INR"),
    strategy: str = Query(default="supertrend", description="Strategy name"),
):
    """
    Run a backtest and return summary + trade log.

    The `df` DataFrame is stripped before serialisation — use the CLI if you need charts.
    """
    if strategy.lower() not in REGISTRY:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown strategy '{strategy}'. Available: {list(REGISTRY.keys())}",
        )

    try:
        result = run_backtest(
            symbol=symbol,
            years=years,
            capital=capital,
            strategy=strategy,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Strip the DataFrame — not JSON-serialisable
    result.pop("df", None)
    return result

# CLAUDE.md — Agent Instructions for market-strategy

This file documents the codebase conventions, architecture decisions, and
working notes for AI coding agents (Claude, Copilot, etc.) working in this repo.

---

## Project Overview

NSE stock strategy backtester. Fetches OHLCV data from NSE via `jugaad-data`,
runs a pluggable strategy, and outputs a trade log + performance summary.
Exposed via a Click CLI (`cli.py`) and a FastAPI REST API (`api.py`).

---

## Environment

- **Python**: 3.11+ — venv at `venv/` (gitignored)
- **OS**: Windows with corporate SSL proxy
- **SSL fix**: Every file that makes HTTPS calls must call `truststore.inject_into_ssl()` at module level
- **pip installs**: Always add `--trusted-host pypi.org --trusted-host files.pythonhosted.org`
- **Activation**: `.\venv\Scripts\Activate.ps1` (requires `RemoteSigned` execution policy)

---

## Key Dependencies

| Package | Purpose |
|---------|---------|
| `jugaad-data` | NSE OHLCV data (equity, series=EQ) |
| `pandas-ta` | ATR calculation (`ta.atr(high, low, close, period=10)`) |
| `mplfinance` | Candlestick charts (volume must be ALL float — enforce with `pd.to_numeric`) |
| `matplotlib` | Performance curve chart |
| `fastapi` + `uvicorn` | REST API |
| `click` | CLI |
| `truststore` | Windows cert store injection for corporate SSL proxy |

---

## Architecture

```
cli.py / api.py
      ↓
  runner.py          # run_backtest(symbol, years, capital, strategy) → dict
      ↓         ↓
  data.py    strategies/REGISTRY
      ↓              ↓
jugaad-data    strategies/supertrend.py → run(df, capital, **kwargs)
                                       → (df, summary_dict, trades_list)
```

---

## Data Layer (`data.py`)

- Cache: `data/{SYMBOL}.csv` — no dates in filename
- Cache hit: cached file covers start→end with up to 5-day slack (weekends/holidays)
- Cache miss: re-fetch from NSE, overwrite cache file
- All timestamps are stripped to tz-naive (`tz_localize(None)`) to avoid comparison errors
- jugaad-data returns verbose column names (`CH_TRADE_HIGH_PRICE` etc.) — mapped with first-match-wins logic to avoid duplicate `volume` column (`CH_TOT_TRADED_QTY` vs `COP_DELIV_QTY`)
- `CH_TIMESTAMP` preferred over `mTIMESTAMP` as date column

### Known jugaad-data bug
`venv/Lib/site-packages/jugaad_data/util.py` line 108 — `os.makedirs` missing `exist_ok=True`.
Patch manually after each fresh venv install:
```python
# change:
os.makedirs(directory)
# to:
os.makedirs(directory, exist_ok=True)
```

---

## Strategy Interface

Every strategy module must expose:

```python
def run(df: pd.DataFrame, capital: float = 100000, **kwargs) -> tuple:
    ...
    return df, summary, trades
```

| Return | Type | Keys |
|--------|------|------|
| `df` | DataFrame | original OHLCV + signals + bands + `cumulative_balance`, `pl`, `cumPL` |
| `summary` | dict | `initial_capital`, `final_balance`, `overall_pl`, `overall_pl_pct`, `peak_balance`, `max_drawdown`, `max_drawdown_pct`, `total_trades` |
| `trades` | list[dict] | `entry_date`, `entry_price`, `exit_date`, `exit_price`, `capital_deployed`, `pl`, `pl_pct` |

Register in `strategies/__init__.py` → REGISTRY.

---

## SuperTrend Strategy (`strategies/supertrend.py`)

- **Settings**: period=10, multiplier=3.0 (TradingView/Zerodha defaults)
- **Long-only**: sell signal exits position; capital sits idle (no shorting)
- **Look-ahead bias removed**: `signals.shift(1)` — signal is only acted on from the *next* bar
- **Band smoothing**: correct upper/lower band logic (only tightens, never widens against trend)
- **P&L calculation**: investment updated *before* calculating P&L on reversal day

### Fixed bugs (do not reintroduce)
1. Investment must be updated at signal change *before* P&L calc (not after)
2. Chained indexing `df['col'][mask] = val` → always use `df.loc[mask, 'col'] = val`
3. Duplicate `volume` column from two `qty` fields in NSE raw data — use first-match-wins col_map

---

## CLI (`cli.py`)

```powershell
python cli.py -s INFY -y 2 --no-chart
```

- `--no-chart` / `--no-chart` skips mplfinance and matplotlib windows (use in scripting/CI)
- `years` is a `click.Choice(["1","2","3"])` — passed as string, cast to `int(years)` in runner call

---

## API (`api.py`)

```powershell
uvicorn api:app --reload
```

- `df` key is stripped from result before JSON response (DataFrame not serialisable)
- `years` validated with `ge=1, le=3` via FastAPI Query
- Docs at `http://localhost:8000/docs`

---

## Common Commands

```powershell
# Run CLI
.\venv\Scripts\python cli.py -s INFY -y 1

# Run API
.\venv\Scripts\uvicorn api:app --reload

# Git push after changes
git add . ; git commit -m "..." ; git push
```

---

## Git

- Remote: `git@github.com:viswesn/market-strategy.git`
- Branch: `main`
- Gitignored: `venv/`, `data/`, `__pycache__/`, `*.pyc`

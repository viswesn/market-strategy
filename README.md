# Market Strategy Backtester

A modular NSE stock strategy backtester with a Click CLI and FastAPI REST interface.
Currently implements the **SuperTrend** indicator (TradingView/Zerodha defaults: period=10, multiplier=3) as a long-only cash equity strategy.

---

## Project Structure

```
market-strategy/
├── data.py                  # NSE data fetching via jugaad-data + CSV cache
├── runner.py                # Orchestrator: fetch → strategy → result dict
├── cli.py                   # Click CLI entry point
├── api.py                   # FastAPI REST entry point
├── strategies/
│   ├── __init__.py          # Strategy registry (REGISTRY dict)
│   └── supertrend.py        # SuperTrend strategy (long-only)
└── data/                    # Cached OHLCV CSVs (auto-created, gitignored)
```

---

## Setup

### Prerequisites
- Python 3.11+
- Windows with corporate SSL proxy → uses `truststore` to inject Windows certificate store

### Install dependencies

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1

pip install jugaad-data pandas pandas-ta mplfinance matplotlib fastapi uvicorn click truststore
```

> If behind a corporate proxy add `--trusted-host pypi.org --trusted-host files.pythonhosted.org` to pip commands.

---

## CLI Usage

```powershell
python cli.py [OPTIONS]

Options:
  -s, --symbol TEXT            NSE stock symbol  [default: INFY]
  -y, --years [1|2|3]          Backtest period in years  [default: 1]
  -c, --capital FLOAT          Initial capital in INR  [default: 100000]
  -t, --strategy [supertrend]  Strategy to run  [default: supertrend]
  --no-chart                   Skip charts (useful for scripting)
  --help                       Show this message and exit.
```

### Examples

```powershell
# 1-year INFY backtest with charts
python cli.py -s INFY -y 1

# 2-year TCS backtest, no charts
python cli.py -s TCS -y 2 --no-chart

# 3-year RELIANCE with ₹2 lakh capital
python cli.py -s RELIANCE -y 3 -c 200000
```

### Sample Output

```
Symbol   : INFY
Strategy : supertrend
Period   : 2025-04-29  →  2026-04-29

===========================================================================
                                 TRADE LOG
===========================================================================
#    Entry         Buy@     Exit        Sell@      Capital      P/L ₹    P/L%
---------------------------------------------------------------------------
1    2025-07-06  1640.00  2025-07-27  1513.90   100,000.00  -3,289.79  -3.29%
...
===========================================================================

Initial Capital  : ₹  100,000.00
Final Balance    : ₹   74,642.03
Overall P/L      : ₹  -25,357.97  (-25.36%)
Peak Balance     : ₹  100,994.74
Max Drawdown     : ₹  -26,352.70  (-26.09%)
Total Trades     : 5
```

---

## API Usage

```powershell
uvicorn api:app --reload
```

Interactive docs: [http://localhost:8000/docs](http://localhost:8000/docs)

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/strategies` | List registered strategies |
| GET | `/backtest` | Run a backtest |

### Query Parameters for `/backtest`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| symbol | string | INFY | NSE stock symbol |
| years | int (1–3) | 1 | Lookback period |
| capital | float | 100000 | Initial capital in INR |
| strategy | string | supertrend | Strategy name |

### Example

```
GET http://localhost:8000/backtest?symbol=TCS&years=2&capital=200000
```

---

## Data Caching

Market data is fetched from NSE via `jugaad-data` and cached to `data/{SYMBOL}.csv`.
Subsequent runs covering the same or shorter date range load from cache instantly.
The `data/` directory is gitignored — CSVs are never committed.

---

## Adding a New Strategy

1. Create `strategies/my_strategy.py` with a `run(df, capital, **kwargs)` function returning `(df, summary_dict, trades_list)`
2. Register it in `strategies/__init__.py`:
   ```python
   from strategies.my_strategy import run as my_strategy_run
   REGISTRY = {
       "supertrend": supertrend_run,
       "my_strategy": my_strategy_run,
   }
   ```
3. The CLI and API pick it up automatically.

---

## SuperTrend Indicator

SuperTrend is a trend-following indicator plotted on price using two parameters:

- **Period** (ATR lookback): `10` (TradingView/Zerodha default)
- **Multiplier**: `3.0` (TradingView/Zerodha default)

**Band calculation:**
$$\text{Basic Upper} = \frac{H+L}{2} + \text{multiplier} \times ATR$$
$$\text{Basic Lower} = \frac{H+L}{2} - \text{multiplier} \times ATR$$

**Signal rules:**
- Close crosses **above** upper band → **BUY**
- Close crosses **below** lower band → **SELL / exit**

This implementation is **long-only** (cash equity, no shorting). When a sell signal fires, the position is exited and capital sits idle until the next buy signal.

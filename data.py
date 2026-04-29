"""
Shared data-fetching module.
Fetches NSE OHLCV data via jugaad-data and caches to data/{SYMBOL}.csv.

Cache strategy:
  - Cache lives at data/{SYMBOL}.csv (no dates in filename).
  - On a cache hit, if the cached data fully covers the requested date range
    the data is sliced and returned without a network call.
  - If the cache is missing or doesn't cover the range, fresh data is fetched
    and the cache is overwritten.
"""

import os
import urllib3
import truststore
from datetime import date
import pandas as pd
from jugaad_data.nse import NSEHistory

truststore.inject_into_ssl()
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DATA_DIR = "data"


def _cache_path(symbol: str) -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    return os.path.join(DATA_DIR, f"{symbol}.csv")


def _load_cache(symbol: str) -> pd.DataFrame | None:
    path = _cache_path(symbol)
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index.name = "date"
    df = df[~df.index.duplicated(keep='last')]
    df.index = df.index.tz_localize(None)
    df['volume'] = pd.to_numeric(df['volume'], errors='coerce').fillna(0).astype(float)
    return df


def fetch_data(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    Fetch NSE equity OHLCV data for a symbol between start_date and end_date.
    Results are cached to data/{SYMBOL}.csv — subsequent calls with a covered
    date range load from cache instantly without a network call.

    Parameters
    ----------
    symbol     : NSE symbol without suffix, e.g. 'INFY', 'TCS'
    start_date : ISO date string 'YYYY-MM-DD'
    end_date   : ISO date string 'YYYY-MM-DD'

    Returns
    -------
    DataFrame with columns: open, high, low, close, volume  (DatetimeIndex)
    """
    start_dt = pd.Timestamp(start_date).tz_localize(None)
    end_dt = pd.Timestamp(end_date).tz_localize(None)

    cached = _load_cache(symbol)
    if cached is not None:
        cache_start = cached.index.min()
        cache_end = cached.index.max()
        # Allow up to 5 calendar days of slack on the end (weekends/holidays)
        if cache_start <= start_dt and (cache_end >= end_dt or (end_dt - cache_end).days <= 5):
            print(f"Loading {symbol} from cache (data/{symbol}.csv)...")
            return cached.loc[start_dt:].copy()
        print(f"Cache for {symbol} doesn't cover requested range — re-fetching...")

    print(f"Fetching {symbol} from NSE ({start_date} to {end_date})...")
    n = NSEHistory()
    raw = n.stock_raw(
        symbol=symbol, series="EQ",
        from_date=date.fromisoformat(start_date),
        to_date=date.fromisoformat(end_date),
    )
    if not raw:
        raise RuntimeError(f"No data returned for '{symbol}'. Check the symbol and date range.")


    df = pd.DataFrame(raw)
    df.columns = [c.lower() for c in df.columns]

    # Prefer 'ch_timestamp' (full date) over 'mtimestamp' (month string)
    date_col = None
    for candidate in ('ch_timestamp', 'date', 'timestamp'):
        if candidate in df.columns:
            date_col = candidate
            break
    if date_col is None:
        date_col = next((c for c in df.columns if 'date' in c or 'timestamp' in c), None)
    if date_col is None:
        raise RuntimeError(f"Cannot find date column. Available columns: {list(df.columns)}")

    df[date_col] = pd.to_datetime(df[date_col]).dt.tz_localize(None)
    df.set_index(date_col, inplace=True)
    df.index.name = "date"
    df.sort_index(inplace=True)

    # Build col_map with first-match-wins to avoid duplicate target columns
    col_map = {}
    mapped_targets: set = set()
    for c in df.columns:
        cl = c.lower()
        target = None
        if 'open' in cl and 'open' not in mapped_targets:
            target = 'open'
        elif 'high' in cl and 'high' not in mapped_targets:
            target = 'high'
        elif 'low' in cl and 'low' not in mapped_targets:
            target = 'low'
        elif ('clos' in cl or cl == 'ltp') and 'close' not in mapped_targets:
            target = 'close'
        elif ('qty' in cl or ('vol' in cl and 'val' not in cl)) and 'volume' not in mapped_targets:
            target = 'volume'
        if target:
            col_map[c] = target
            mapped_targets.add(target)
    df.rename(columns=col_map, inplace=True)

    df = df[['open', 'high', 'low', 'close', 'volume']]
    df = df[~df.index.duplicated(keep='last')]
    df['volume'] = pd.to_numeric(df['volume'], errors='coerce').fillna(0).astype(float)

    cache_file = _cache_path(symbol)
    df.to_csv(cache_file)
    print(f"Saved to {cache_file}")
    return df.loc[start_dt:end_dt].copy()

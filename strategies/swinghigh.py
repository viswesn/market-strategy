"""
Swing High Retest strategy for NSE equity.

Pattern: Price forms a swing high → pulls back → retests that high zone → breaks out.

Entry (BUY):
    Close comes within `proximity_pct` (default 5%) of the rolling `swing_period`-bar high
    AND close is above EMA(50) (uptrend filter)
    AND volume is above its rolling average (momentum confirmation)

Exit (SELL):
    Hard stop: close drops more than `stop_pct` (default 3%) below the swing high level
    that was being retested at entry.  If price falls back below old resistance, the
    breakout has failed — exit immediately.
    OR trailing stop: close drops more than `trail_pct` (default 10%) from the highest
    close recorded since entry.

Strategy name: swinghigh
"""

import numpy as np
import pandas as pd
import pandas_ta as ta


def _compute_indicators(
    df: pd.DataFrame,
    swing_period: int = 40,
    ema_period: int = 50,
    vol_period: int = 20,
) -> pd.DataFrame:
    df = df.copy()
    # Swing high: rolling max of previous `swing_period` bars' highs (no look-ahead)
    df['swing_high'] = df['high'].shift(1).rolling(swing_period).max()
    df['ema50'] = ta.ema(df['close'], length=ema_period)
    df['vol_avg'] = df['volume'].shift(1).rolling(vol_period).mean()
    df.dropna(inplace=True)
    return df


def _generate_signals(
    df: pd.DataFrame,
    proximity_pct: float = 5.0,
    stop_pct: float = 3.0,
    trail_pct: float = 10.0,
) -> pd.DataFrame:
    """
    State-machine signal generator (no look-ahead bias).

    Flat → Long : close within proximity_pct% of swing_high, above EMA50, volume above avg
    Long → Flat : close drops stop_pct% below swing_high_at_entry (breakout failed)
                  OR trailing stop from post-entry peak
    """
    in_trade = False
    entry_price = None
    swing_high_at_entry = None
    max_close = None
    signals = []
    entry_swing_highs = []   # parallel list to build df column

    for i in range(len(df)):
        close      = df['close'].iloc[i]
        swing_high = df['swing_high'].iloc[i]
        ema        = df['ema50'].iloc[i]
        volume     = df['volume'].iloc[i]
        vol_avg    = df['vol_avg'].iloc[i]

        if not in_trade:
            # Distance from swing high (positive = below high, negative = above high)
            pct_from_high = (swing_high - close) / swing_high * 100
            in_zone       = -proximity_pct <= pct_from_high <= proximity_pct
            trend_ok      = close > ema
            volume_ok     = volume >= vol_avg  # at least average volume

            if in_zone and trend_ok and volume_ok:
                signals.append(1)
                in_trade = True
                entry_price = close
                swing_high_at_entry = swing_high   # remember the level we retested
                max_close = close
                entry_swing_highs.append(swing_high_at_entry)
            else:
                signals.append(-1)
                entry_swing_highs.append(np.nan)
        else:
            max_close = max(max_close, close)
            trail_stop = max_close * (1 - trail_pct / 100)
            # Hard stop: price falls back below old resistance → breakout failed
            hard_stop  = swing_high_at_entry * (1 - stop_pct / 100)
            stop_level = max(trail_stop, hard_stop)

            if close < stop_level:
                signals.append(-1)
                in_trade = False
                entry_price = None
                swing_high_at_entry = None
                max_close = None
                entry_swing_highs.append(np.nan)
            else:
                signals.append(1)
                entry_swing_highs.append(swing_high_at_entry)

    df['signals'] = signals
    df['entry_swing_high'] = entry_swing_highs
    df['signals'] = df['signals'].shift(1)  # remove look-ahead bias
    return df


def _create_positions(df: pd.DataFrame) -> pd.DataFrame:
    buy_positions  = [np.nan] * len(df)
    sell_positions = [np.nan] * len(df)

    for i in range(1, len(df)):
        cur  = df['signals'].iloc[i]
        prev = df['signals'].iloc[i - 1]
        if cur == 1 and prev != 1:
            buy_positions[i]  = df['close'].iloc[i]
        elif cur == -1 and prev == 1:
            sell_positions[i] = df['close'].iloc[i]

    df['buy_positions']  = buy_positions
    df['sell_positions'] = sell_positions
    return df


def _calc_performance(df: pd.DataFrame, capital: float):
    cumulative_balance = capital
    investment   = capital
    peak_balance = capital
    max_drawdown = 0.0
    max_drawdown_pct = 0.0

    balance_list    = [capital]
    pnl_list        = [0.0]
    investment_list = [capital]

    trades = []
    entry_date = entry_price = entry_cap = entry_swing_high = None

    for index in range(1, len(df)):
        row         = df.iloc[index]
        prev_signal = df.iloc[index - 1]['signals']

        if row['signals'] != prev_signal:
            investment = cumulative_balance

            # Close previous BUY trade
            if prev_signal == 1 and entry_date is not None:
                trade_pl = cumulative_balance - entry_cap
                trades.append({
                    "entry_date":          str(entry_date),
                    "entry_price":         round(entry_price, 2),
                    "exit_date":           str(row.name.date()),
                    "exit_price":          round(float(row['open']), 2),
                    "capital_deployed":    round(entry_cap, 2),
                    "pl":                  round(trade_pl, 2),
                    "pl_pct":              round(trade_pl / entry_cap * 100, 2),
                    "swing_high_at_entry": round(entry_swing_high, 2) if entry_swing_high else None,
                })
                entry_date = None

            # Open new BUY trade
            if row['signals'] == 1:
                entry_date        = row.name.date()
                entry_price       = float(row['open'])
                entry_cap         = cumulative_balance
                entry_swing_high  = float(row['swing_high'])

        # Long-only P&L
        pl = ((row['close'] - row['open']) / row['open']) * investment if row['signals'] == 1 else 0.0
        cumulative_balance += pl
        balance_list.append(cumulative_balance)
        pnl_list.append(pl)
        investment_list.append(investment)

        drawdown = cumulative_balance - peak_balance
        if drawdown < max_drawdown:
            max_drawdown     = drawdown
            max_drawdown_pct = (max_drawdown / peak_balance) * 100
        if cumulative_balance > peak_balance:
            peak_balance = cumulative_balance

    # Close any still-open trade at end of data
    if entry_date is not None:
        last     = df.iloc[-1]
        trade_pl = cumulative_balance - entry_cap
        trades.append({
            "entry_date":          str(entry_date),
            "entry_price":         round(entry_price, 2),
            "exit_date":           str(last.name.date()),
            "exit_price":          round(float(last['close']), 2),
            "capital_deployed":    round(entry_cap, 2),
            "pl":                  round(trade_pl, 2),
            "pl_pct":              round(trade_pl / entry_cap * 100, 2),
            "swing_high_at_entry": round(entry_swing_high, 2) if entry_swing_high else None,
        })

    df['investment']        = investment_list
    df['cumulative_balance'] = balance_list
    df['pl']                = pnl_list
    df['cumPL']             = df['pl'].cumsum()

    overall_pl = cumulative_balance - capital
    summary = {
        "initial_capital":  round(capital, 2),
        "final_balance":    round(cumulative_balance, 2),
        "overall_pl":       round(overall_pl, 2),
        "overall_pl_pct":   round(overall_pl / capital * 100, 2),
        "peak_balance":     round(peak_balance, 2),
        "max_drawdown":     round(max_drawdown, 2),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "total_trades":     len(trades),
    }
    return df, summary, trades


def run(
    df: pd.DataFrame,
    capital: float = 100000,
    swing_period: int = 40,
    ema_period: int = 50,
    vol_period: int = 20,
    proximity_pct: float = 5.0,
    stop_pct: float = 3.0,
    trail_pct: float = 10.0,
    **kwargs,
):
    """
    Run the Swing High Retest strategy (long-only, cash equity).

    Parameters
    ----------
    df            : OHLCV DataFrame with columns open/high/low/close/volume
    capital       : Initial capital in INR (default 1 lakh)
    swing_period  : Bars to look back for swing high (default 40 ≈ 2 months)
    ema_period    : EMA trend-filter period (default 50)
    vol_period    : Volume average period for confirmation (default 20)
    proximity_pct : % within swing high to trigger entry (default 5)
    stop_pct      : Hard stop % below the swing high level at entry (default 3).
                    Exit when price breaks back below old resistance (breakout failed).
    trail_pct     : Trailing stop % from post-entry peak (default 10)

    Returns
    -------
    (df_with_signals, summary_dict, trades_list)
    """
    df = _compute_indicators(df, swing_period=swing_period, ema_period=ema_period, vol_period=vol_period)
    df = _generate_signals(df, proximity_pct=proximity_pct, stop_pct=stop_pct, trail_pct=trail_pct)
    df = _create_positions(df)
    df, summary, trades = _calc_performance(df, capital=capital)
    return df, summary, trades

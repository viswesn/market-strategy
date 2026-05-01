"""
Swing High Retest strategy for NSE equity.

Pattern
-------
  X : A significant price peak (local swing high) forms in history.
      The price then pulls back meaningfully below X.
  B : Price climbs back up and retests the X level (within proximity_pct%).
      This bar is the BUY signal — resistance becoming support.

Entry  : Open of the bar AFTER the B bar (no look-ahead).
Stop   : 3% below the entry price  (if price drops, exit fast).
Profit : 5% above the entry price  (take the move, wait for next swing).

The same X level is never traded twice — once a B fires from X, the
next trade waits for a fresh, higher swing high to form.

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
    profit_pct: float = 5.0,
    lookback_period: int = 120,
    min_pullback_pct: float = 8.0,
) -> pd.DataFrame:
    """
    State-machine (no look-ahead bias).

    FLAT → IN_TRADE when:
      - Dominant high in the lookback window is X (the historical peak)
      - Price pulled back min_pullback_pct% below X after that bar
      - Current close came back within proximity_pct% of X level (retest = B bar)
      - Close > EMA50 and volume >= vol_avg
      - The same X bar is never traded twice (last_x_abs guard)

    lookback_period : bars back to look for X (default 120 ≈ 6 months).
                      Uses max(0, i - lookback_period) so early bars in the
                      dataset still work with whatever history they have.

    IN_TRADE → FLAT when:
      - Close >= entry * (1 + profit_pct/100)   [take-profit, 5% from buy price]
      - Close <  entry * (1 - stop_pct/100)     [stop-loss,   3% from buy price]
    """
    in_trade    = False
    entry_price = None
    x_level_in  = None
    last_x_abs  = -1          # index of the X bar last traded, prevents re-entry

    signals           = []
    entry_swing_highs = []
    sh_bar_dates      = []

    for i in range(len(df)):
        # Need at least 40 bars of history before signals can fire
        if i < 40:
            signals.append(-1)
            entry_swing_highs.append(np.nan)
            sh_bar_dates.append(pd.NaT)
            continue

        close   = df['close'].iloc[i]
        ema     = df['ema50'].iloc[i]
        volume  = df['volume'].iloc[i]
        vol_avg = df['vol_avg'].iloc[i]

        # Skip if indicators are still NaN (warm-up period)
        if pd.isna(ema) or pd.isna(vol_avg):
            signals.append(-1)
            entry_swing_highs.append(np.nan)
            sh_bar_dates.append(pd.NaT)
            continue

        if not in_trade:
            # --- B must be a new higher high (local peak) ---
            # B's high must be >= the high of the 3 bars immediately before it.
            b_high = float(df['high'].iloc[i])
            if i >= 3 and b_high < float(df['high'].iloc[i - 3:i].max()):
                signals.append(-1)
                entry_swing_highs.append(np.nan)
                sh_bar_dates.append(pd.NaT)
                continue

            # --- Scan for X: bars at least 40 bars before B ---
            # X must be a historical swing peak that:
            #   (a) is ≥40 bars before today (enforced by lb_end)
            #   (b) is a local swing high (highest in its ±3 bar window)
            #   (c) was a new higher high when it formed (higher than 20 bars before it)
            #   (d) B's high is within proximity_pct% of X's high  (price is retesting that level)
            #   (e) price pulled back at least min_pullback_pct% AFTER X and BEFORE B
            lb_start = max(0, i - lookback_period)
            lb_end   = max(0, i - 40)       # X must be ≥40 bars before B
            candidates = []                 # list of (bar_index, high)

            for j in range(lb_start, lb_end):
                h = float(df['high'].iloc[j])

                # X must be a local swing high: highest in its ±3 bar window
                win_s = max(0, j - 3)
                win_e = min(len(df), j + 4)
                if h < float(df['high'].iloc[win_s:win_e].max()):
                    continue

                # X must have been a new higher high: higher than the 20 bars before it
                prev_s = max(0, j - 20)
                if prev_s < j and h <= float(df['high'].iloc[prev_s:j].max()):
                    continue

                # Never trade the same X bar twice
                if j == last_x_abs:
                    continue

                # B's HIGH must be within proximity_pct% of X's high (retest of resistance)
                pct = abs(b_high - h) / h * 100
                if pct > proximity_pct:
                    continue

                # Require real pullback from X: lowest close after X must be
                # at least min_pullback_pct% below X's high
                if j + 1 < i:
                    min_close_after = float(df['close'].iloc[j + 1:i].min())
                else:
                    min_close_after = close
                pb = (h - min_close_after) / h * 100
                if pb >= min_pullback_pct:
                    candidates.append((j, h))

            if not candidates:
                signals.append(-1)
                entry_swing_highs.append(np.nan)
                sh_bar_dates.append(pd.NaT)
                continue

            # Pick the candidate with the highest high (strongest resistance level)
            x_abs, x_level = max(candidates, key=lambda c: c[1])

            # Confirm entry: trend and volume filters
            trend_ok = close > ema
            vol_ok   = volume >= vol_avg

            if trend_ok and vol_ok:
                signals.append(1)
                entry_swing_highs.append(x_level)
                sh_bar_dates.append(df.index[x_abs])
                in_trade    = True
                entry_price = close
                x_level_in  = x_level
                last_x_abs  = x_abs
            else:
                signals.append(-1)
                entry_swing_highs.append(np.nan)
                sh_bar_dates.append(pd.NaT)

        else:  # IN_TRADE
            take_profit = entry_price * (1 + profit_pct / 100)
            stop        = entry_price * (1 - stop_pct  / 100)

            if close >= take_profit or close < stop:
                signals.append(-1)
                in_trade    = False
                entry_price = None
                x_level_in  = None
                entry_swing_highs.append(np.nan)
                sh_bar_dates.append(pd.NaT)
            else:
                signals.append(1)
                entry_swing_highs.append(x_level_in)
                sh_bar_dates.append(pd.NaT)

    df['signals']          = signals
    df['entry_swing_high'] = entry_swing_highs
    df['sh_bar_date']      = sh_bar_dates
    df['signals']          = df['signals'].shift(1)   # no look-ahead
    return df


def _create_positions(df: pd.DataFrame) -> pd.DataFrame:
    buy_positions   = [np.nan] * len(df)
    sell_positions  = [np.nan] * len(df)
    break_positions = [np.nan] * len(df)   # bar where retest was detected (one before buy)

    for i in range(1, len(df)):
        cur  = df['signals'].iloc[i]
        prev = df['signals'].iloc[i - 1]
        if cur == 1 and prev != 1:
            buy_positions[i]     = df['close'].iloc[i]       # entry bar (next day)
            break_positions[i-1] = df['high'].iloc[i-1]      # detection bar (X on high)
        elif cur == -1 and prev == 1:
            sell_positions[i] = df['close'].iloc[i]

    df['buy_positions']   = buy_positions
    df['sell_positions']  = sell_positions
    df['break_positions'] = break_positions
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
    entry_date = entry_price = entry_cap = entry_swing_high = swing_high_bar_date = None

    for index in range(1, len(df)):
        row         = df.iloc[index]
        prev_signal = df.iloc[index - 1]['signals']

        if row['signals'] != prev_signal:
            investment = cumulative_balance

            # Close previous BUY trade
            if prev_signal == 1 and entry_date is not None:
                trade_pl = cumulative_balance - entry_cap
                trades.append({
                    "entry_date":           str(entry_date),
                    "entry_price":          round(entry_price, 2),
                    "exit_date":            str(row.name.date()),
                    "exit_price":           round(float(row['open']), 2),
                    "capital_deployed":     round(entry_cap, 2),
                    "pl":                   round(trade_pl, 2),
                    "pl_pct":               round(trade_pl / entry_cap * 100, 2),
                    "swing_high_at_entry":  round(entry_swing_high, 2) if entry_swing_high else None,
                    "swing_high_bar_date":  swing_high_bar_date,
                    "stop_level":           round(entry_price * (1 - 0.03), 2),
                })
                entry_date = None

            # Open new BUY trade
            if row['signals'] == 1:
                entry_date        = row.name.date()
                entry_price       = float(row['open'])
                entry_cap         = cumulative_balance
                # X level and X bar date from the detection bar (before the 1-bar shift)
                esh = df['entry_swing_high'].iloc[index - 1]
                entry_swing_high  = float(esh) if pd.notna(esh) else None
                sh_raw = df['sh_bar_date'].iloc[index - 1]
                swing_high_bar_date = str(sh_raw.date()) if pd.notna(sh_raw) else None

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
            "entry_date":           str(entry_date),
            "entry_price":          round(entry_price, 2),
            "exit_date":            str(last.name.date()),
            "exit_price":           round(float(last['close']), 2),
            "capital_deployed":     round(entry_cap, 2),
            "pl":                   round(trade_pl, 2),
            "pl_pct":               round(trade_pl / entry_cap * 100, 2),
            "swing_high_at_entry":  round(entry_swing_high, 2) if entry_swing_high else None,
            "swing_high_bar_date":  swing_high_bar_date,
            "stop_level":           round(entry_price * (1 - 0.03), 2),
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
    profit_pct: float = 5.0,
    lookback_period: int = 120,
    min_pullback_pct: float = 8.0,
    **kwargs,
):
    """
    Run the Swing High Retest strategy (long-only, cash equity).

    Parameters
    ----------
    swing_period     : Rolling-max window for the chart line (default 40)
    ema_period       : EMA trend-filter period (default 50)
    vol_period       : Volume average period (default 20)
    proximity_pct    : % within X level to trigger B entry (default 5)
    stop_pct         : Stop-loss % below B entry price (default 3)
    profit_pct       : Take-profit % above B entry price (default 5)
    lookback_period  : Bars to look back for dominant swing high X (default 120 ≈ 6 months)
    min_pullback_pct : Minimum % pullback from X before B is valid (default 8)
    """
    df = _compute_indicators(df, swing_period=swing_period,
                             ema_period=ema_period, vol_period=vol_period)
    df = _generate_signals(df, proximity_pct=proximity_pct, stop_pct=stop_pct,
                           profit_pct=profit_pct, lookback_period=lookback_period,
                           min_pullback_pct=min_pullback_pct)
    df = _create_positions(df)
    df, summary, trades = _calc_performance(df, capital=capital)
    return df, summary, trades

"""
Swing Trade strategy for NSE equity.

Entry (BUY):  RSI(14) crosses UP through rsi_buy (default 40) AND close > EMA(50)
              — recovering from oversold while still in an uptrend.
Exit  (SELL): RSI(14) reaches rsi_sell (default 70) [overbought]
              OR close drops below EMA(50) [uptrend broken].

Long-only (cash equity, no shorting). Capital sits idle between trades.

Parameters (all overridable via CLI/API kwargs):
    rsi_period : RSI lookback period (default 14)
    ema_period : EMA trend-filter period (default 50)
    rsi_buy    : RSI crossover level that triggers entry (default 40)
    rsi_sell   : RSI level that triggers exit (default 70)
"""

import numpy as np
import pandas as pd
import pandas_ta as ta


def _compute_indicators(
    df: pd.DataFrame,
    rsi_period: int = 14,
    ema_period: int = 50,
) -> pd.DataFrame:
    df = df.copy()
    df['rsi'] = ta.rsi(df['close'], length=rsi_period)
    df['ema50'] = ta.ema(df['close'], length=ema_period)
    df.dropna(inplace=True)
    return df


def _generate_signals(
    df: pd.DataFrame,
    rsi_buy: float = 40.0,
    rsi_sell: float = 70.0,
) -> pd.DataFrame:
    """
    State-machine signal generator (no look-ahead bias).

    Flat  → Long  : RSI crosses above rsi_buy AND close > ema50
    Long  → Flat  : RSI >= rsi_sell OR close < ema50
    """
    in_trade = False
    raw = []

    for i in range(len(df)):
        rsi = df['rsi'].iloc[i]
        prev_rsi = df['rsi'].iloc[i - 1] if i > 0 else rsi
        close = df['close'].iloc[i]
        prev_close = df['close'].iloc[i - 1] if i > 0 else close
        ema = df['ema50'].iloc[i]
        prev_ema = df['ema50'].iloc[i - 1] if i > 0 else ema

        if not in_trade:
            # Entry condition 1: RSI crosses above rsi_buy from below AND price in uptrend
            rsi_crossover = prev_rsi < rsi_buy and rsi >= rsi_buy and close > ema
            # Entry condition 2: close crosses above EMA50 from below while RSI shows momentum
            ema_breakout = prev_close <= prev_ema and close > ema and rsi > rsi_buy
            if rsi_crossover or ema_breakout:
                raw.append(1)
                in_trade = True
            else:
                raw.append(-1)
        else:
            # Exit: overbought OR trend broken
            if rsi >= rsi_sell or close < ema:
                raw.append(-1)
                in_trade = False
            else:
                raw.append(1)

    df['signals'] = raw
    df['signals'] = df['signals'].shift(1)  # remove look-ahead bias
    return df


def _create_positions(df: pd.DataFrame) -> pd.DataFrame:
    buy_positions = [np.nan] * len(df)
    sell_positions = [np.nan] * len(df)

    for i in range(1, len(df)):
        cur = df['signals'].iloc[i]
        prev = df['signals'].iloc[i - 1]
        if cur == 1 and prev != 1:
            buy_positions[i] = df['close'].iloc[i]
        elif cur == -1 and prev == 1:
            sell_positions[i] = df['close'].iloc[i]

    df['buy_positions'] = buy_positions
    df['sell_positions'] = sell_positions
    return df


def _calc_performance(df: pd.DataFrame, capital: float):
    cumulative_balance = capital
    investment = capital
    peak_balance = capital
    max_drawdown = 0.0
    max_drawdown_pct = 0.0

    balance_list = [capital]
    pnl_list = [0.0]
    investment_list = [capital]

    trades = []
    entry_date = entry_price = entry_cap = None

    for index in range(1, len(df)):
        row = df.iloc[index]
        prev_signal = df.iloc[index - 1]['signals']

        if row['signals'] != prev_signal:
            investment = cumulative_balance

            # Close previous BUY trade
            if prev_signal == 1 and entry_date is not None:
                trade_pl = cumulative_balance - entry_cap
                trades.append({
                    "entry_date": str(entry_date),
                    "entry_price": round(entry_price, 2),
                    "exit_date": str(row.name.date()),
                    "exit_price": round(float(row['open']), 2),
                    "capital_deployed": round(entry_cap, 2),
                    "pl": round(trade_pl, 2),
                    "pl_pct": round(trade_pl / entry_cap * 100, 2),
                })
                entry_date = None

            # Open new BUY trade
            if row['signals'] == 1:
                entry_date = row.name.date()
                entry_price = float(row['open'])
                entry_cap = cumulative_balance

        # Long-only P&L
        if row['signals'] == 1:
            pl = ((row['close'] - row['open']) / row['open']) * investment
        else:
            pl = 0.0

        cumulative_balance += pl
        balance_list.append(cumulative_balance)
        pnl_list.append(pl)
        investment_list.append(investment)

        drawdown = cumulative_balance - peak_balance
        if drawdown < max_drawdown:
            max_drawdown = drawdown
            max_drawdown_pct = (max_drawdown / peak_balance) * 100
        if cumulative_balance > peak_balance:
            peak_balance = cumulative_balance

    # Close any still-open trade at end of data
    if entry_date is not None:
        last = df.iloc[-1]
        trade_pl = cumulative_balance - entry_cap
        trades.append({
            "entry_date": str(entry_date),
            "entry_price": round(entry_price, 2),
            "exit_date": str(last.name.date()),
            "exit_price": round(float(last['close']), 2),
            "capital_deployed": round(entry_cap, 2),
            "pl": round(trade_pl, 2),
            "pl_pct": round(trade_pl / entry_cap * 100, 2),
        })

    df['investment'] = investment_list
    df['cumulative_balance'] = balance_list
    df['pl'] = pnl_list
    df['cumPL'] = df['pl'].cumsum()

    overall_pl = cumulative_balance - capital
    summary = {
        "initial_capital": round(capital, 2),
        "final_balance": round(cumulative_balance, 2),
        "overall_pl": round(overall_pl, 2),
        "overall_pl_pct": round(overall_pl / capital * 100, 2),
        "peak_balance": round(peak_balance, 2),
        "max_drawdown": round(max_drawdown, 2),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "total_trades": len(trades),
    }
    return df, summary, trades


def run(
    df: pd.DataFrame,
    capital: float = 100000,
    rsi_period: int = 14,
    ema_period: int = 50,
    rsi_buy: float = 40.0,
    rsi_sell: float = 70.0,
    **kwargs,
):
    """
    Run the Swing Trade strategy (long-only, cash equity).

    Parameters
    ----------
    df         : OHLCV DataFrame with columns open/high/low/close/volume
    capital    : Initial capital in INR (default 1 lakh)
    rsi_period : RSI lookback period (default 14)
    ema_period : EMA trend-filter period (default 50)
    rsi_buy    : RSI crossover level for entry (default 40)
    rsi_sell   : RSI level for exit / overbought (default 70)

    Returns
    -------
    (df_with_signals, summary_dict, trades_list)
    """
    df = _compute_indicators(df, rsi_period=rsi_period, ema_period=ema_period)
    df = _generate_signals(df, rsi_buy=rsi_buy, rsi_sell=rsi_sell)
    df = _create_positions(df)
    df, summary, trades = _calc_performance(df, capital=capital)
    return df, summary, trades

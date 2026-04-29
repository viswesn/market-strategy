"""
SuperTrend strategy implementation.

Exposes a single run(df, capital, **kwargs) function that the runner calls.
To add a new strategy, create a new module here with the same interface.
"""

import numpy as np
import pandas as pd
import pandas_ta as ta


def _compute_bands(df: pd.DataFrame, atr_period: int = 10, atr_multiplier: float = 3.0) -> pd.DataFrame:
    df = df.copy()
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], period=atr_period)
    df.dropna(inplace=True)
    hl2 = (df['high'] + df['low']) / 2  # recomputed after dropna
    df['basicUpperband'] = hl2 + atr_multiplier * df['atr']
    df['basicLowerband'] = hl2 - atr_multiplier * df['atr']

    ub = [df['basicUpperband'].iloc[0]]
    lb = [df['basicLowerband'].iloc[0]]
    for i in range(1, len(df)):
        ub.append(
            df['basicUpperband'].iloc[i]
            if df['basicUpperband'].iloc[i] < ub[i - 1] or df['close'].iloc[i - 1] > ub[i - 1]
            else ub[i - 1]
        )
        lb.append(
            df['basicLowerband'].iloc[i]
            if df['basicLowerband'].iloc[i] > lb[i - 1] or df['close'].iloc[i - 1] < lb[i - 1]
            else lb[i - 1]
        )

    df['upperband'] = ub
    df['lowerband'] = lb
    df.drop(['basicUpperband', 'basicLowerband'], axis=1, inplace=True)
    return df


def _generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    signals = [0]
    for i in range(1, len(df)):
        if df['close'].iloc[i] > df['upperband'].iloc[i]:
            signals.append(1)
        elif df['close'].iloc[i] < df['lowerband'].iloc[i]:
            signals.append(-1)
        else:
            signals.append(signals[i - 1])
    df['signals'] = signals
    df['signals'] = df['signals'].shift(1)  # remove look-ahead bias
    return df


def _create_positions(df: pd.DataFrame) -> pd.DataFrame:
    df.loc[df['signals'] == 1, 'upperband'] = np.nan
    df.loc[df['signals'] == -1, 'lowerband'] = np.nan

    buy_positions = [np.nan]
    sell_positions = [np.nan]
    for i in range(1, len(df)):
        if df['signals'].iloc[i] == 1 and df['signals'].iloc[i] != df['signals'].iloc[i - 1]:
            buy_positions.append(df['close'].iloc[i])
            sell_positions.append(np.nan)
        elif df['signals'].iloc[i] == -1 and df['signals'].iloc[i] != df['signals'].iloc[i - 1]:
            sell_positions.append(df['close'].iloc[i])
            buy_positions.append(np.nan)
        else:
            buy_positions.append(np.nan)
            sell_positions.append(np.nan)

    df['buy_positions'] = buy_positions
    df['sell_positions'] = sell_positions
    return df


def _calc_performance(df: pd.DataFrame, capital: float, leverage: float = 1.0):
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

        # Update investment at start of each new signal (before calculating P/L)
        if row['signals'] != prev_signal:
            investment = cumulative_balance

            # Close the previous BUY trade
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

            # Open a new BUY trade
            if row['signals'] == 1:
                entry_date = row.name.date()
                entry_price = float(row['open'])
                entry_cap = cumulative_balance

        # Long-only: profit on BUY signal, idle on SELL signal
        if row['signals'] == 1:
            pl = ((row['close'] - row['open']) / row['open']) * investment * leverage
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

    # Close any still-open BUY trade at end of data
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


def run(df: pd.DataFrame, capital: float = 100000, atr_period: int = 10,
        atr_multiplier: float = 3.0, **kwargs):
    """
    Run the SuperTrend strategy (long-only, cash equity).

    Parameters
    ----------
    df            : OHLCV DataFrame with columns open/high/low/close/volume
    capital       : Initial capital in INR (default 1 lakh)
    atr_period    : ATR lookback period (default 10, TradingView/Zerodha standard)
    atr_multiplier: Band multiplier (default 3.0, TradingView/Zerodha standard)

    Returns
    -------
    (df_with_signals, summary_dict, trades_list)
    """
    df = _compute_bands(df, atr_period=atr_period, atr_multiplier=atr_multiplier)
    df = _generate_signals(df)
    df = _create_positions(df)
    df, summary, trades = _calc_performance(df, capital=capital)
    return df, summary, trades

"""
CLI entry point — run backtests from the terminal using Click.

Usage examples:
    python cli.py
    python cli.py --symbol TCS --years 2 --capital 200000
    python cli.py --symbol RELIANCE --years 3 --strategy supertrend --no-chart
"""

import sys
import click
import pandas as pd
import mplfinance as mpf
import matplotlib.pyplot as plt

from runner import run_backtest
from strategies import REGISTRY

STRATEGY_CHOICES = click.Choice(list(REGISTRY.keys()), case_sensitive=False)


def _print_results(result: dict) -> None:
    s = result["summary"]
    trades = result["trades"]
    period = result["period"]

    print(f"\nSymbol   : {result['symbol']}")
    print(f"Strategy : {result['strategy']}")
    print(f"Period   : {period['start']}  →  {period['end']}")

    print("\n" + "=" * 75)
    print(f"{'TRADE LOG':^75}")
    print("=" * 75)
    print(
        f"{'#':<4} {'Entry':^12} {'Buy@':>8} {'Exit':^12} {'Sell@':>8}"
        f" {'Capital':>12} {'P/L ₹':>10} {'P/L%':>7}"
    )
    print("-" * 75)

    if not trades:
        print("  No trades were executed in this period.")
    for i, t in enumerate(trades, 1):
        print(
            f"{i:<4} {t['entry_date']:<12} {t['entry_price']:>8.2f}"
            f" {t['exit_date']:<12} {t['exit_price']:>8.2f}"
            f" {t['capital_deployed']:>12,.2f}"
            f" {t['pl']:>10,.2f} {t['pl_pct']:>6.2f}%"
        )

    print("=" * 75)
    print(f"\nInitial Capital  : ₹{s['initial_capital']:>12,.2f}")
    print(f"Final Balance    : ₹{s['final_balance']:>12,.2f}")
    print(f"Overall P/L      : ₹{s['overall_pl']:>12,.2f}  ({s['overall_pl_pct']:.2f}%)")
    print(f"Peak Balance     : ₹{s['peak_balance']:>12,.2f}")
    print(f"Max Drawdown     : ₹{s['max_drawdown']:>12,.2f}  ({s['max_drawdown_pct']:.2f}%)")
    print(f"Total Trades     : {s['total_trades']}")


def _plot_performance_curve(df, symbol: str, capital: float) -> None:
    plt.figure()
    plt.plot(df.index, df['cumulative_balance'], label='Portfolio Balance', color='steelblue')
    plt.axhline(y=capital, color='gray', linestyle='--', label='Initial Capital')
    plt.fill_between(df.index, capital, df['cumulative_balance'],
                     where=(df['cumulative_balance'] >= capital), alpha=0.2, color='green')
    plt.fill_between(df.index, capital, df['cumulative_balance'],
                     where=(df['cumulative_balance'] < capital), alpha=0.2, color='red')
    plt.title(f"{symbol} Performance Curve")
    plt.xlabel("Date")
    plt.ylabel("Balance (₹)")
    plt.xticks(rotation=45)
    plt.legend()
    plt.tight_layout()
    plt.show()


def _plot_supertrend(result: dict) -> None:
    df = result["df"]
    symbol = result["symbol"]
    capital = result["capital"]

    apd = [
        mpf.make_addplot(df['lowerband'], label="Lower Band", color='green'),
        mpf.make_addplot(df['upperband'], label="Upper Band", color='red'),
        mpf.make_addplot(df['buy_positions'],  type='scatter', marker='^',
                         label="Buy",  markersize=80, color='#2cf651'),
        mpf.make_addplot(df['sell_positions'], type='scatter', marker='v',
                         label="Sell", markersize=80, color='#f50100'),
    ]
    fills = [
        dict(y1=df['close'].values, y2=df['lowerband'].values, panel=0, alpha=0.3, color="#CCFFCC"),
        dict(y1=df['close'].values, y2=df['upperband'].values, panel=0, alpha=0.3, color="#FFCCCC"),
    ]
    mpf.plot(df, addplot=apd, type='candle', volume=True, style='charles',
             xrotation=20, title=f"{symbol} SuperTrend", fill_between=fills)

    _plot_performance_curve(df, symbol, capital)


def _plot_swingtrade(result: dict) -> None:
    df = result["df"]
    symbol = result["symbol"]
    capital = result["capital"]

    # RSI panel — fill NaN so mplfinance doesn't complain
    rsi = df['rsi'].copy()
    rsi_buy_line = pd.Series(40.0, index=df.index)
    rsi_sell_line = pd.Series(70.0, index=df.index)

    apd = [
        mpf.make_addplot(df['ema50'], label="EMA 50", color='orange', width=1.5),
        mpf.make_addplot(df['buy_positions'],  type='scatter', marker='^',
                         label="Buy",  markersize=80, color='#2cf651'),
        mpf.make_addplot(df['sell_positions'], type='scatter', marker='v',
                         label="Sell", markersize=80, color='#f50100'),
        mpf.make_addplot(rsi,           panel=2, label="RSI(14)", color='purple', ylabel="RSI"),
        mpf.make_addplot(rsi_buy_line,  panel=2, label="RSI Buy (40)",  color='green',
                         linestyle='--', width=0.8),
        mpf.make_addplot(rsi_sell_line, panel=2, label="RSI Sell (70)", color='red',
                         linestyle='--', width=0.8),
    ]
    mpf.plot(df, addplot=apd, type='candle', volume=True, style='charles',
             xrotation=20, title=f"{symbol} Swing Trade",
             panel_ratios=(4, 1, 2))

    _plot_performance_curve(df, symbol, capital)


def _plot_swinghigh(result: dict) -> None:
    df     = result["df"]
    symbol = result["symbol"]
    capital = result["capital"]
    trades  = result["trades"]

    # Only EMA + swing-high line; numbered markers are drawn manually below
    apd = [
        mpf.make_addplot(df['swing_high'], label="Swing High", color='purple',
                         linestyle='--', width=1.0),
        mpf.make_addplot(df['ema50'], label="EMA 50", color='steelblue', width=1.2),
    ]

    fig, axes = mpf.plot(
        df, addplot=apd, type='candle', volume=True, style='charles',
        xrotation=20, title=f"{symbol} Swing High Retest",
        returnfig=True,
    )
    ax = axes[0]   # main price panel

    # Mild pastel colors — one per trade, cycling
    zone_colors = ['#AED6F1', '#A9DFBF', '#FAD7A0', '#D7BDE2', '#FADADD',
                   '#A2D9CE', '#F9E79F', '#D2B4DE', '#F1948A', '#85C1E9']

    for i, trade in enumerate(trades):
        swing_h = trade.get('swing_high_at_entry')
        if swing_h is None:
            continue

        n     = i + 1           # trade number shown in both icons
        color = zone_colors[i % len(zone_colors)]

        # Integer x-positions (mplfinance uses integer axis for candles)
        entry_pos = int(df.index.searchsorted(pd.Timestamp(trade['entry_date'])))
        exit_pos  = int(df.index.searchsorted(pd.Timestamp(trade['exit_date'])))
        exit_pos  = min(exit_pos, len(df) - 1)

        # X bar = the actual bar that FORMED the swing high (can be weeks before entry)
        sh_bar_date = trade.get('swing_high_bar_date')
        x_pos = int(df.index.searchsorted(pd.Timestamp(sh_bar_date))) if sh_bar_date else max(entry_pos - 1, 0)

        # ── Shaded vertical band from X bar through exit ────────────────────
        ax.axvspan(x_pos - 0.5, exit_pos + 0.5, alpha=0.10, color=color, zorder=0)

        # ── Swing-high dashed line from X to exit ────────────────────────
        x_start = max(x_pos - 2, 0)
        x_end   = min(exit_pos + 3, len(df) - 1)
        ax.hlines(swing_h, x_start, x_end,
                  colors=color, linestyles='--', linewidth=1.8, zorder=2)
        ax.text(
            entry_pos + 0.5, swing_h,
            f"  SH:{swing_h:.0f}",
            fontsize=7, va='bottom', color='navy', zorder=3,
            bbox=dict(boxstyle='round,pad=0.12', facecolor=color,
                      alpha=0.55, edgecolor='none'),
        )

        # ── Stop line: 3% below ENTRY price (from trade dict) ─────────────
        stop_level = trade.get('stop_level') or (trade['entry_price'] * 0.97)
        ax.hlines(stop_level, x_start, x_end,
                  colors='red', linestyles=':', linewidth=1.1, zorder=2)

        # ── X{n} badge — orange, sits above the swing-high formation bar ─
        x_bar_high = float(df['high'].iloc[x_pos])
        y_range    = ax.get_ylim()
        offset     = (y_range[1] - y_range[0]) * 0.018
        ax.annotate(
            f"✕{n}",
            xy=(x_pos, x_bar_high + offset),
            fontsize=8, fontweight='bold', color='white',
            ha='center', va='bottom', zorder=6,
            bbox=dict(boxstyle='round,pad=0.28', facecolor='#E87000',
                      edgecolor='white', linewidth=0.6),
        )

        # ── ▲{n} badge — green, sits below the entry bar low ─────────────
        entry_low = float(df['low'].iloc[entry_pos])
        ax.annotate(
            f"▲{n}",
            xy=(entry_pos, entry_low - offset),
            fontsize=8, fontweight='bold', color='white',
            ha='center', va='top', zorder=6,
            bbox=dict(boxstyle='round,pad=0.28', facecolor='#18A558',
                      edgecolor='white', linewidth=0.6),
        )

    plt.tight_layout()
    plt.show()
    _plot_performance_curve(df, symbol, capital)


def _plot(result: dict) -> None:
    strategy = result["strategy"]
    if strategy == "swingtrade":
        _plot_swingtrade(result)
    elif strategy == "swinghigh":
        _plot_swinghigh(result)
    else:
        _plot_supertrend(result)


@click.command()
@click.option(
    "-s", "--symbol",
    default="INFY", show_default=True,
    help="NSE stock symbol (e.g. INFY, TCS, RELIANCE, HDFCBANK)",
)
@click.option(
    "-y", "--years",
    default=1, show_default=True,
    type=click.Choice(["1", "2", "3"]),
    help="Backtest period in years (max 3)",
)
@click.option(
    "-c", "--capital",
    default=100000, show_default=True,
    type=float,
    help="Initial capital in INR",
)
@click.option(
    "-t", "--strategy",
    default="supertrend", show_default=True,
    type=STRATEGY_CHOICES,
    help="Strategy to run",
)
@click.option(
    "--no-chart",
    is_flag=True, default=False,
    help="Skip charts (useful for scripting)",
)
def main(symbol, years, capital, strategy, no_chart):
    """
    NSE Stock Strategy Backtester

    Runs a backtest for an NSE-listed stock using the selected strategy
    and prints a detailed trade log + performance summary.
    """
    try:
        result = run_backtest(
            symbol=symbol,
            years=int(years),
            capital=capital,
            strategy=strategy,
        )
        _print_results(result)
        if not no_chart:
            _plot(result)
    except (ValueError, RuntimeError) as e:
        click.echo(f"\nError: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

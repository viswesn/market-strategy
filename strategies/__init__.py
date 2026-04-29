from strategies.supertrend import run as supertrend_run
from strategies.swingtrade import run as swingtrade_run

# Registry maps strategy name → run(df, capital, **kwargs) function.
# Add new strategies here when you create them.
REGISTRY: dict = {
    "supertrend": supertrend_run,
    "swingtrade": swingtrade_run,
}

from __future__ import annotations
import math
import numpy as np
import pandas as pd
from .quant import add_features


def _metrics(equity: pd.Series, returns: pd.Series, trades: int, turnover: float, periods_per_year: int, gross_total: float, transaction_costs: float):
    r = returns.dropna()
    total = equity.iloc[-1] / equity.iloc[0] - 1
    ann_ret = (1 + total) ** (periods_per_year / max(len(r), 1)) - 1 if len(r) else np.nan
    ann_vol = r.std(ddof=1) * math.sqrt(periods_per_year) if len(r) > 1 else np.nan
    sharpe = (r.mean() / r.std(ddof=1) * math.sqrt(periods_per_year)) if len(r) > 1 and r.std(ddof=1) > 0 else np.nan
    peak = equity.cummax()
    dd = equity / peak - 1
    mdd = dd.min()
    return {
        "total_return": float(total), "annualized_return": float(ann_ret),
        "annualized_volatility": float(ann_vol), "sharpe": float(sharpe),
        "max_drawdown": float(mdd), "calmar": float(ann_ret / abs(mdd)) if mdd < 0 else np.nan,
        "win_rate": float((r > 0).mean()) if len(r) else np.nan,
        "trades": int(trades), "turnover": float(turnover),
        "gross_return": float(gross_total), "transaction_costs": float(transaction_costs), "net_return": float(total)
    }


def backtest(df: pd.DataFrame, strategy: str, initial=10000.0, fee=0.001, params=None, periods_per_year=365):
    params = params or {}
    x = add_features(df).dropna().copy()
    if x.empty:
        raise ValueError("Not enough data after feature warmup")
    close = x["close"]
    if strategy == "buy_hold":
        target = pd.Series(1.0, index=x.index)
    elif strategy == "sma_crossover":
        fast = close.rolling(int(params.get("fast", 10))).mean()
        slow = close.rolling(int(params.get("slow", 30))).mean()
        target = (fast > slow).astype(float)
    elif strategy == "momentum":
        target = (x["momentum_20"] > 0).astype(float)
    elif strategy == "mean_reversion":
        target = (x["zscore_20"] < -0.5).astype(float)
    elif strategy == "quant_composite":
        s = np.tanh(3*x["ret_20"].fillna(0)) + np.tanh(5*x["sma_20_gap"].fillna(0)) - 0.5*np.tanh(x["zscore_20"].fillna(0))
        target = (s > float(params.get("threshold", 0.0))).astype(float)
    else:
        raise ValueError("Unknown strategy")

    # Execute next bar: current signal cannot see the future.
    pos = target.shift(1).fillna(0)
    asset_ret = close.pct_change().fillna(0)
    changes = pos.diff().abs().fillna(pos.abs())
    costs = changes * fee
    gross_ret_series = pos * asset_ret
    strat_ret = gross_ret_series - costs
    gross_equity = initial * (1 + gross_ret_series).cumprod()
    equity = initial * (1 + strat_ret).cumprod()
    trades = int((changes > 0).sum())
    turnover = float(changes.sum())
    transaction_costs = float((costs * equity.shift(1).fillna(initial)).sum())
    gross_total = float(gross_equity.iloc[-1] / initial - 1)
    m = _metrics(equity, strat_ret, trades, turnover, periods_per_year, gross_total, transaction_costs)
    return {
        "metrics": m,
        "equity": [{"t": str(i), "value": float(v)} for i,v in equity.items()],
        "drawdown": [{"t": str(i), "value": float(v / equity.loc[:i].max() - 1)} for i,v in equity.items()],
    }

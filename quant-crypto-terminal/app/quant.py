from __future__ import annotations
import math
import numpy as np
import pandas as pd


def rsi(series: pd.Series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = -delta.clip(upper=0).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    x["ret_1"] = x["close"].pct_change(1)
    x["ret_5"] = x["close"].pct_change(5)
    x["ret_20"] = x["close"].pct_change(20)
    x["log_ret_1"] = np.log(x["close"]).diff()
    x["momentum_20"] = x["close"] / x["close"].shift(20) - 1
    sma = x["close"].rolling(20).mean()
    ema = x["close"].ewm(span=20, adjust=False).mean()
    x["sma_20_gap"] = x["close"] / sma - 1
    x["ema_20_gap"] = x["close"] / ema - 1
    x["vol_20"] = x["ret_1"].rolling(20).std()
    x["realized_vol_20"] = x["log_ret_1"].rolling(20).std() * math.sqrt(365)
    x["vol_regime"] = x["vol_20"] / x["vol_20"].rolling(100).median()
    x["rsi_14"] = rsi(x["close"])
    x["volume_change"] = x["volume"].pct_change()
    vma = x["volume"].rolling(20).mean()
    x["volume_sma_gap"] = x["volume"] / vma - 1
    mu = x["close"].rolling(20).mean()
    sd = x["close"].rolling(20).std()
    x["zscore_20"] = (x["close"] - mu) / sd
    return x.replace([np.inf, -np.inf], np.nan)


def squash(x):
    return float(np.tanh(np.nan_to_num(x, nan=0.0)))


def compute_signals(df: pd.DataFrame) -> dict:
    f = add_features(df)
    last = f.iloc[-1]
    momentum = squash(3 * float(last.get("ret_20", 0)))
    trend = squash(5 * float(np.nan_to_num((last.get("sma_20_gap", 0) + last.get("ema_20_gap", 0)) / 2)))
    mean_rev = squash(-0.75 * float(last.get("zscore_20", 0)))
    vol = squash(-2 * float(last.get("vol_regime", 0) - 1))
    # Baseline weights are intentionally fixed and documented: trend/momentum receive more weight,
    # mean-reversion and volatility are secondary diversifiers. Users can change them in the research UI.
    composite = 0.35*momentum + 0.35*trend + 0.20*mean_rev + 0.10*vol
    return {
        "momentum": momentum, "trend": trend, "mean_reversion": mean_rev,
        "volatility": vol, "composite": float(np.clip(composite, -1, 1)),
        "rsi": float(last.get("rsi_14", np.nan)), "realized_vol": float(last.get("realized_vol_20", np.nan)),
        "ret_1": float(last.get("ret_1", np.nan)), "ret_20": float(last.get("ret_20", np.nan)),
    }

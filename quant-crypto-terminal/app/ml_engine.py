from __future__ import annotations
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score
from .config import FEATURES
from .quant import add_features


def prepare(df: pd.DataFrame, horizon=5, threshold=0.0):
    f = add_features(df)
    f["future_return"] = f["close"].shift(-horizon) / f["close"] - 1
    f["target"] = (f["future_return"] > threshold).astype(int)
    return f


def walk_forward(df: pd.DataFrame, horizon=5, threshold=0.0, min_train=300):
    data = prepare(df, horizon, threshold).dropna(subset=["target"])
    data = data.iloc[:-horizon] if len(data) > horizon else data
    X = data[FEATURES]
    y = data["target"]
    probs, preds, ys = [], [], []
    model = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scale", StandardScaler()),
        ("model", LogisticRegression(max_iter=2000, class_weight="balanced")),
    ])
    # Expanding-window evaluation, retraining at fixed monthly-ish chunks.
    step = max(20, min_train // 5)
    starts = range(min_train, len(data), step)
    coeff = None
    for end in starts:
        test_end = min(end + step, len(data))
        if test_end <= end: break
        model.fit(X.iloc[:end], y.iloc[:end])
        p = model.predict_proba(X.iloc[end:test_end])[:,1]
        probs.extend(p.tolist()); preds.extend((p >= 0.5).astype(int).tolist()); ys.extend(y.iloc[end:test_end].tolist())
    metrics = {}
    if ys:
        metrics = {
            "accuracy": accuracy_score(ys, preds),
            "precision": precision_score(ys, preds, zero_division=0),
            "recall": recall_score(ys, preds, zero_division=0),
            "f1": f1_score(ys, preds, zero_division=0),
            "roc_auc": roc_auc_score(ys, probs) if len(set(ys)) > 1 else None,
        }
    # Fit final model on all available training rows for current estimate.
    model.fit(X, y)
    coef = model.named_steps["model"].coef_[0]
    coeff = sorted([{"feature": n, "coefficient": float(c)} for n,c in zip(FEATURES, coef)], key=lambda z: abs(z["coefficient"]), reverse=True)
    latest = float(model.predict_proba(X.iloc[[-1]])[:,1][0])
    signal = "bullish" if latest > 0.60 else "bearish" if latest < 0.40 else "neutral"
    return {
        "probability": latest,
        "signal": signal,
        "metrics": metrics,
        "coefficients": coeff,
        "method": "Logistic Regression + expanding walk-forward evaluation",
        "horizon": horizon, "threshold": threshold, "feature_count": len(FEATURES),
    }

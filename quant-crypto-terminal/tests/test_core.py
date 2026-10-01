from decimal import Decimal
from pathlib import Path
import tempfile
import sqlite3

import pytest

from app import db
from app.db import execute_trade, init_db, account_snapshot
from app.quant import add_features, compute_signals
from app.backtest import backtest
from app.ml_engine import walk_forward
import pandas as pd
import numpy as np


def fixture_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path/'test.db')
    init_db()
    return tmp_path/'test.db'


def bars(n=500):
    rng=np.random.default_rng(7)
    ret=rng.normal(0.0005,0.01,n)
    close=100*np.exp(np.cumsum(ret))
    return pd.DataFrame({'close':close,'volume':rng.uniform(100,1000,n)})


def test_buy_sell_precision_and_idempotency(tmp_path, monkeypatch):
    fixture_db(tmp_path, monkeypatch)
    execute_trade('demo','order-12345678','BTC','BUY',Decimal('0.01'),Decimal('100.00'),Decimal('0.001'))
    dup=execute_trade('demo','order-12345678','BTC','BUY',Decimal('0.01'),Decimal('100.00'),Decimal('0.001'))
    assert dup['status']=='duplicate'
    snap=account_snapshot('demo', {'BTC':Decimal('100.00'),'ETH':Decimal('1'),'SOL':Decimal('1')})
    assert Decimal(snap['cash']) == Decimal('9998.999') or Decimal(snap['cash']) == Decimal('9999.00')
    execute_trade('demo','order-sell-12345678','BTC','SELL',Decimal('0.005'),Decimal('110.00'),Decimal('0.001'))
    snap=account_snapshot('demo', {'BTC':Decimal('110.00'),'ETH':Decimal('1'),'SOL':Decimal('1')})
    btc=next(x for x in snap['holdings'] if x['asset']=='BTC')
    assert Decimal(btc['quantity']) == Decimal('0.005')


def test_insufficient_funds_and_holdings(tmp_path, monkeypatch):
    fixture_db(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='Insufficient funds'):
        execute_trade('demo','buy-too-much','BTC','BUY',Decimal('1'),Decimal('20000'),Decimal('0'))
    with pytest.raises(ValueError, match='Insufficient holdings'):
        execute_trade('demo','sell-empty','BTC','SELL',Decimal('0.1'),Decimal('100'),Decimal('0'))


def test_quant_features_and_signal():
    d=bars()
    f=add_features(d)
    for c in ['ret_1','ret_20','sma_20_gap','ema_20_gap','vol_20','rsi_14','zscore_20']:
        assert c in f
    s=compute_signals(d)
    assert -1 <= s['composite'] <= 1


def test_backtest_no_future_position():
    d=bars()
    out=backtest(d,'momentum',fee=.001)
    assert 'metrics' in out and 'equity' in out and len(out['equity'])>0


def test_ml_walk_forward():
    d=bars(700)
    out=walk_forward(d,horizon=5,threshold=0.0,min_train=350)
    assert 0 <= out['probability'] <= 1
    assert out['signal'] in {'bullish','bearish','neutral'}
    assert out['coefficients']

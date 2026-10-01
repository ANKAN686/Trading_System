from __future__ import annotations
import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd
from fastapi import FastAPI, HTTPException, Request as FRequest
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .config import DEFAULT_FEE, BINANCE_SYMBOLS, REST_KLINES, SUPPORTED_ASSETS
from .db import account_snapshot, execute_trade, init_db
from .market import MarketDataService
from .quant import compute_signals
from .backtest import backtest
from .ml_engine import walk_forward

market = MarketDataService()

@asynccontextmanager
async def lifespan(app):
    init_db()
    await market.start()
    try:
        yield
    finally:
        await market.stop()

app = FastAPI(title="Quantitative Crypto Trading Terminal", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

class OrderIn(BaseModel):
    asset: str
    side: str
    quantity: str = Field(min_length=1, max_length=40)
    client_order_id: str = Field(min_length=8, max_length=80)

    @field_validator("asset")
    @classmethod
    def asset_ok(cls, v):
        v = v.upper()
        if v not in SUPPORTED_ASSETS: raise ValueError("Unsupported asset")
        return v
    @field_validator("side")
    @classmethod
    def side_ok(cls, v):
        v = v.upper()
        if v not in {"BUY","SELL"}: raise ValueError("Invalid side")
        return v

class ResearchIn(BaseModel):
    asset: str
    interval: str = "1h"
    limit: int = Field(default=1000, ge=200, le=1000)
    strategy: str = "quant_composite"
    fee: float = Field(default=float(DEFAULT_FEE), ge=0, le=0.05)
    horizon: int = Field(default=5, ge=1, le=50)
    threshold: float = Field(default=0.0, ge=-0.5, le=0.5)

    @field_validator("asset")
    @classmethod
    def asset_ok(cls,v):
        v=v.upper();
        if v not in SUPPORTED_ASSETS: raise ValueError("Unsupported asset")
        return v

@app.get("/")
async def root():
    return FileResponse("static/index.html")

@app.get("/api/health")
async def health():
    return {"ok": True, "market_source": {a: q.get("source") for a,q in market.public().items()}}

@app.get("/api/market")
async def market_api():
    return {"quotes": market.public(), "as_of": datetime.now(timezone.utc).isoformat()}

@app.get("/api/portfolio")
async def portfolio():
    return account_snapshot("demo", market.prices())

@app.post("/api/orders")
async def order(body: OrderIn):
    try:
        qty = Decimal(body.quantity)
        price = market.prices().get(body.asset)
        if price is None:
            raise HTTPException(status_code=503, detail="Live market price unavailable or stale")
        result = execute_trade("demo", body.client_order_id, body.asset, body.side, qty, price, DEFAULT_FEE)
        return {**result, "execution_price": str(price)}
    except HTTPException: raise
    except (InvalidOperation, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/stream")
async def stream():
    q = market.subscribe()
    async def gen():
        try:
            while True:
                payload = await q.get()
                yield f"data: {json.dumps(payload)}\n\n"
        except asyncio.CancelledError:
            return
        finally:
            market.unsubscribe(q)
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})


def get_klines(symbol, interval, limit):
    params = urlencode({"symbol": symbol, "interval": interval, "limit": limit})
    req = Request(f"{REST_KLINES}?{params}", headers={"User-Agent":"quant-terminal/1.0"})
    with urlopen(req, timeout=15) as r:
        rows = json.load(r)
    cols=["open_time","open","high","low","close","volume","close_time","quote_volume","trades","taker_base","taker_quote","ignore"]
    df=pd.DataFrame(rows, columns=cols)
    for c in ["open","high","low","close","volume"]: df[c]=pd.to_numeric(df[c], errors="coerce")
    df["time"]=pd.to_datetime(df["open_time"], unit="ms", utc=True)
    return df.dropna(subset=["close","volume"])

@app.post("/api/research")
async def research(body: ResearchIn):
    try:
        df = await asyncio.to_thread(get_klines, BINANCE_SYMBOLS[body.asset], body.interval, body.limit)
        signals = compute_signals(df)
        periods = {"1m": 525600, "5m": 105120, "15m": 35040, "30m": 17520, "1h": 8760, "2h": 4380, "4h": 2190, "6h": 1460, "8h": 1095, "12h": 730, "1d": 365}.get(body.interval, 365)
        bt = backtest(df, body.strategy, fee=body.fee, periods_per_year=periods)
        ml = walk_forward(df, horizon=body.horizon, threshold=body.threshold)
        chart=[{"t": t.isoformat(), "close": float(c), "volume": float(v)} for t,c,v in zip(df["time"].tail(300), df["close"].tail(300), df["volume"].tail(300))]
        return {"asset": body.asset, "signals": signals, "backtest": bt, "ml": ml, "chart": chart}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Research data unavailable: {e}")

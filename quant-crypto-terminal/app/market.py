import asyncio
import json
import time
from dataclasses import dataclass, asdict
from decimal import Decimal
from typing import Callable
from urllib.request import Request, urlopen

import websockets

from .config import BINANCE_SYMBOLS, REST_TICKER, STALE_AFTER_MS, WS_URL

@dataclass
class Quote:
    asset: str
    price: Decimal
    change24h: Decimal = Decimal("0")
    volume24h: Decimal = Decimal("0")
    ts_ms: int = 0
    source: str = ""

    def to_public(self):
        age = max(0, int(time.time() * 1000) - self.ts_ms) if self.ts_ms else None
        return {**asdict(self), "price": str(self.price), "change24h": str(self.change24h), "volume24h": str(self.volume24h), "age_ms": age, "stale": bool(age is not None and age > STALE_AFTER_MS)}

class MarketDataService:
    def __init__(self):
        self.quotes: dict[str, Quote] = {}
        self.clients: set[asyncio.Queue] = set()
        self.stop_event = asyncio.Event()
        self.task = None

    async def start(self):
        self.task = asyncio.create_task(self._run())

    async def stop(self):
        self.stop_event.set()
        if self.task:
            self.task.cancel()

    def subscribe(self):
        q = asyncio.Queue(maxsize=20)
        self.clients.add(q)
        return q

    def unsubscribe(self, q):
        self.clients.discard(q)

    async def _broadcast(self):
        payload = {a: q.to_public() for a, q in self.quotes.items()}
        for q in list(self.clients):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass

    async def _run(self):
        backoff = 1
        while not self.stop_event.is_set():
            try:
                async with websockets.connect(WS_URL, ping_interval=20, ping_timeout=20, open_timeout=10) as ws:
                    backoff = 1
                    async for raw in ws:
                        msg = json.loads(raw)
                        data = msg.get("data", msg)
                        symbol = data.get("s", "")
                        if symbol not in BINANCE_SYMBOLS.values():
                            continue
                        asset = next(a for a, s in BINANCE_SYMBOLS.items() if s == symbol)
                        try:
                            px = Decimal(str(data["p"]))
                            qty = Decimal(str(data.get("q", "0")))
                        except Exception:
                            continue
                        if px <= 0 or not px.is_finite():
                            continue
                        self.quotes[asset] = Quote(asset, px, ts_ms=int(data.get("T", time.time()*1000)), source="binance_ws")
                        # Volume/change are refreshed opportunistically via the quote endpoint.
                        await self._broadcast()
            except asyncio.CancelledError:
                return
            except Exception:
                await self._refresh_rest()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def _refresh_rest(self):
        def fetch():
            req = Request(REST_TICKER, headers={"User-Agent": "quant-terminal/1.0"})
            with urlopen(req, timeout=8) as r:
                return json.load(r)
        try:
            data = await asyncio.to_thread(fetch)
            wanted = {v for v in BINANCE_SYMBOLS.values()}
            for row in data:
                if row.get("symbol") not in wanted:
                    continue
                asset = next(a for a,s in BINANCE_SYMBOLS.items() if s == row["symbol"])
                self.quotes[asset] = Quote(asset,
                    Decimal(str(row["lastPrice"])),
                    Decimal(str(row.get("priceChangePercent", "0"))),
                    Decimal(str(row.get("volume", "0"))),
                    int(time.time()*1000),
                    "binance_rest")
            await self._broadcast()
        except Exception:
            pass

    def prices(self):
        return {a: q.price for a,q in self.quotes.items() if not self._is_stale(q)}

    def _is_stale(self, q):
        return (time.time()*1000 - q.ts_ms) > STALE_AFTER_MS

    def public(self):
        return {a: q.to_public() for a,q in self.quotes.items()}

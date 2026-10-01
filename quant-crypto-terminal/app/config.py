from decimal import Decimal
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "terminal.db"

INITIAL_CASH = Decimal("10000.00")
SUPPORTED_ASSETS = {"BTC", "ETH", "SOL"}
BINANCE_SYMBOLS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}
WS_URL = "wss://stream.binance.com:9443/stream?streams=btcusdt@trade/ethusdt@trade/solusdt@trade"
REST_KLINES = "https://data-api.binance.vision/api/v3/klines"
REST_TICKER = "https://data-api.binance.vision/api/v3/ticker/24hr"
STALE_AFTER_MS = 15_000
DEFAULT_FEE = Decimal("0.001")  # 10 bps baseline assumption for paper simulation
RISK_FREE_RATE = Decimal("0")
TRADING_DAYS = 365

FEATURES = [
    "ret_1", "ret_5", "ret_20", "log_ret_1", "momentum_20",
    "sma_20_gap", "ema_20_gap", "vol_20", "realized_vol_20",
    "vol_regime", "rsi_14", "volume_change", "volume_sma_gap",
    "zscore_20",
]

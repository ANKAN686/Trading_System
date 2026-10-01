# Quantitative Crypto Trading Simulator + ML Research Platform

A research-oriented crypto paper-trading terminal for **BTC, ETH, and SOL**. The project combines real public market data, a server-authoritative paper-trading engine, quantitative feature engineering, signal generation, historical backtesting, and an interpretable machine-learning research pipeline.

> **Educational / research project. No real-money trading is performed.**

## Why I built it

I wanted to build something closer to a small quantitative research terminal than a conventional crypto dashboard. The main engineering problem is not drawing prices on a screen; it is keeping **market data, portfolio state, execution logic, backtesting, and ML research separated and internally consistent**.

The system therefore has two distinct data paths:

```text
LIVE PATH
Binance trade stream / REST fallback
            ↓
     MarketDataService
            ↓
   server-side quote cache
            ↓
     paper trading + SSE
            ↓
        dashboard

RESEARCH PATH
Binance historical klines
            ↓
       pandas DataFrame
            ↓
     feature engineering
            ↓
 signals / backtest / walk-forward ML
            ↓
        dashboard
```

The codebase separates these paths so that a temporary live-feed problem does not silently contaminate historical research.

## Main features

### Live market data
- BTC/USDT, ETH/USDT, SOL/USDT
- Binance public market-data WebSocket
- REST fallback
- stale-price detection
- reconnect/backoff logic
- invalid-price rejection

### Paper trading
- $10,000 initial virtual cash
- server-side execution price
- BUY / SELL market orders
- server-side validation
- integer-based financial storage
- idempotency keys
- SQLite transactional order execution
- realized and unrealized P&L
- trade history

### Quantitative research
- simple returns
- log returns
- rolling returns
- momentum
- SMA / EMA gaps
- rolling volatility
- realized volatility
- volatility regime
- RSI
- volume change and volume/SMA gap
- rolling z-score
- normalized component signals
- composite quant score

### Machine learning
- configurable future-return classification target
- Logistic Regression baseline
- median imputation + standardization
- expanding-window chronological walk-forward evaluation
- probability output
- bullish / neutral / bearish signal
- accuracy, precision, recall, F1 and ROC-AUC
- coefficient-based explainability

### Backtesting
- Buy & Hold
- SMA crossover
- Momentum
- Mean Reversion
- Quant Composite
- next-bar execution
- configurable transaction fee
- gross vs net return
- annualized return / volatility
- Sharpe ratio
- maximum drawdown
- Calmar ratio
- win rate
- trade count
- turnover
- equity and drawdown curves

## Architecture

```text
                    Binance Public Data
                    /               \
              WebSocket             REST
                  |                historical
                  v                   |
          +----------------+          |
          | MarketData     |          |
          | Service        |          v
          +-------+--------+   +--------------+
                  |             | Research     |
          +-------+-------+     | Pipeline     |
          | Quote Cache   |     +------+-------+
          +---+-------+---+            |
              |       |                v
              |       |         +-------------+
              |       +-------->| Quant       |
              |                 | Features    |
              |                 +------+------+ 
              |                        |
              v                        +-------> Signals
       +-------------+                         
       | Trading     |                    +----> Backtest
       | Engine      |                    |
       +------+------+                    +----> Walk-forward ML
              |
              v
       +-------------+
       | SQLite      |
       | Ledger      |
       +------+------+ 
              |
              +------------------+
                                 v
                         FastAPI API / SSE
                                 |
                                 v
                         Browser Dashboard
```

The FastAPI layer is the application boundary. The browser does not own portfolio state or execution pricing.

## Tech stack

- **Backend:** Python, FastAPI, Uvicorn
- **Market data:** Binance public REST + WebSocket
- **Storage:** SQLite with WAL mode
- **Numerical research:** NumPy, pandas
- **ML:** scikit-learn
- **Frontend:** browser-native HTML/CSS/JavaScript
- **Charts:** Canvas-based lightweight rendering in the current build
- **Testing:** pytest + FastAPI TestClient

The repository intentionally keeps the system small rather than introducing unnecessary microservices. The live market path, trading path, and research path are modules inside one application.

## Project structure

```text
quant-crypto-terminal/
├── app/
│   ├── backtest.py      # historical strategy simulation + metrics
│   ├── config.py        # symbols, endpoints, fees, feature list
│   ├── db.py            # SQLite schema + atomic trading logic
│   ├── main.py          # FastAPI application + API routes
│   ├── market.py        # WebSocket/REST market-data service
│   ├── ml_engine.py     # walk-forward Logistic Regression
│   └── quant.py         # feature engineering + signals
├── static/
│   ├── index.html       # dashboard layout
│   ├── app.js           # browser state + API calls + rendering
│   └── styles.css       # terminal-style UI
├── tests/
│   ├── test_core.py     # quant, backtest, ML, trading tests
│   └── test_api.py      # HTTP + concurrency tests
├── data/                # local SQLite database at runtime
├── README.md
├── requirements.txt
├── package.json
└── run.py
```

## Quick start

### Windows PowerShell

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python run.py
```

Open:

```text
http://127.0.0.1:8000
```

### Tests

```powershell
pytest -q
```

## API

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/health` | application + market-source status |
| GET | `/api/market` | current server-side quote cache |
| GET | `/api/portfolio` | portfolio snapshot |
| POST | `/api/orders` | execute a paper BUY/SELL |
| GET | `/api/stream` | Server-Sent Events for market updates |
| POST | `/api/research` | historical features + signals + backtest + ML |

### Order request

```json
{
  "asset": "BTC",
  "side": "BUY",
  "quantity": "0.01",
  "client_order_id": "unique-client-order-id"
}
```

The browser does **not** send the execution price. The backend reads a current non-stale market price from its own cache and computes notional and fees server-side.

## Financial-state design

The database stores:

- USD cash in integer cents
- token quantities in smallest supported units
- price in micro-USD
- fees in cents

Trades use a unique `client_order_id` to make retries idempotent. SQLite `BEGIN IMMEDIATE` transactions are used so two concurrent order requests cannot both spend the same cash or exceed available holdings.

## Quant assumptions

Baseline assumptions in the current build:

- paper/backtest fee: **0.10% per trade**
- risk-free rate: **0%** for educational Sharpe calculations
- default ML horizon: **5 bars**
- default ML classification threshold: future return > 0
- ML signal thresholds: probability > 0.60 bullish, < 0.40 bearish, otherwise neutral
- price freshness window: **15 seconds**

Composite quant score:

```text
0.35 × momentum
+ 0.35 × trend
+ 0.20 × mean-reversion
+ 0.10 × volatility
```

The baseline weights are explicit and documented rather than presented as an optimized or statistically proven optimum.

## ML methodology

The baseline model is Logistic Regression. The target asks whether the return over the next `N` bars exceeds a configurable threshold. Features are generated only from information available at the prediction timestamp.

Evaluation is expanding-window and chronological rather than randomly shuffled:

```text
Train [t0 ........ tK]
                 ↓
              Validate

Train [t0 ........ tK+Δ]
                       ↓
                    Validate

... continue through the evaluation period
```

This is designed to reduce the main leakage failure mode in time-series research: letting future observations influence earlier training or preprocessing.

## Backtesting methodology

Signals are generated on bar `t` and the target position is applied on the next bar. Transaction costs are applied when the position changes. Both gross and net outcomes are reported.

This means a backtest is not simply:

```text
signal × same-bar return
```

but instead:

```text
signal(t)
   ↓
position(t+1)
   ↓
return(t+1)
   ↓
transaction cost
```

## Limitations

The current repository is a **single-user educational simulator**, not a production exchange execution system.

Current limitations include:

- one demo account (`demo`)
- no authentication or multi-user isolation
- no real-money trading
- single-asset baseline backtests
- percentage fee model rather than order-book slippage
- browser-native frontend instead of a React/Next.js build
- live Internet connectivity is required for live/historical Binance data

These limitations are intentional in the current educational scope; the architecture leaves room for later upgrades.

## Disclaimer

This software is for education and quantitative research. Model estimates and backtest results are not guarantees of future performance. No real-money trading is enabled by this project.

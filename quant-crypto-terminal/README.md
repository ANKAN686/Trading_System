# Quantitative Crypto Trading Simulator + ML Research Platform

A self-contained educational quantitative trading terminal for paper trading BTC, ETH, and SOL with real public market data, a SQLite-backed trading ledger, modular quantitative signals, walk-forward ML research, and historical backtesting.

## Architecture

```text
Binance WebSocket / REST
        |
        v
 Market Data Service ----> Server-Sent Events ----> Browser dashboard
        |
        +----> Trading Engine ----> SQLite ledger
        |
        +----> Quant Feature Engine ----> Signals
        |
        +----> Historical Research ----> Backtest
                                      |
                                      +----> Logistic Regression
                                                |
                                                +----> ML signal + coefficients
```

The live and historical paths are intentionally separate. Paper-order pricing is always taken from the server-side market cache; the browser sends only asset, side, quantity, and an idempotency key.

## Tech stack

- FastAPI + Uvicorn backend
- SQLite with WAL mode and `BEGIN IMMEDIATE` order transactions
- Browser-side HTML/CSS/JavaScript dashboard
- Binance public WebSocket market stream for live prices with REST fallback
- pandas / NumPy / scikit-learn for quantitative research
- No real-money trading and no exchange credentials

Next.js 16.3.8 is the current Active LTS as of this project build, but the environment available for this build did not have a functioning Node dependency installation path, so the dashboard is implemented as a self-contained browser client rather than adding an unverified build chain. Next.js official support information: https://nextjs.org/support-policy

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Open `http://127.0.0.1:8000`.

No API key is required for public Binance market data. Network access is required at runtime for live/historical market data.

## Core API

- `GET /api/health`
- `GET /api/market`
- `GET /api/portfolio`
- `POST /api/orders`
- `GET /api/stream` (SSE)
- `POST /api/research`

## Trading correctness

- Initial virtual cash: $10,000.
- Server validates symbol, quantity, price freshness, funds/holdings, and recomputes order notional.
- Financial state is stored as integer cents and integer token smallest units rather than binary floating point.
- Every order requires an idempotency key stored under a UNIQUE constraint.
- SQLite `BEGIN IMMEDIATE` prevents concurrent writes from spending the same cash or overselling the same position.
- Fees are charged server-side.

## Quant methodology

The baseline feature set includes simple/log returns, rolling returns, momentum, SMA/EMA gaps, realized and rolling volatility, volatility regime, RSI, volume features, and rolling z-score.

Baseline signal components are normalized to approximately [-1, +1]. The baseline composite is:

`0.35 * momentum + 0.35 * trend + 0.20 * mean_reversion + 0.10 * volatility`

These weights are explicit, configurable in the research layer, and documented rather than randomly chosen.

## ML methodology

Target: whether the next `N` bars' return exceeds a configurable threshold.

Model: Logistic Regression inside an imputation + standardization pipeline.

Validation: expanding-window chronological walk-forward evaluation. No random shuffling, future features, or future normalization are used.

The UI reports model probability as an estimate, not a guaranteed price forecast. It also exposes model coefficients for interpretability.

## Backtesting

Strategies included:

- Buy & Hold
- SMA crossover
- Momentum
- Mean reversion
- Quant composite

The engine executes a signal on the following bar, applies transaction costs, and reports total/annualized return, annualized volatility, Sharpe, maximum drawdown, Calmar (when defined), win rate, trade count, turnover, gross return, transaction costs, and net return.

## Important quantitative assumptions

- Baseline paper/backtest fee: 0.10% per trade.
- Risk-free rate: 0% for educational Sharpe calculations.
- Annualization: the research engine maps the selected bar interval to its expected periods/year (for example 8,760 for 1h and 365 for 1d).
- ML horizon: 5 bars by default.
- ML probability thresholds: >0.60 bullish, <0.40 bearish, otherwise neutral.
- Portfolio marks use the latest non-stale server quote.

## Testing

Run:

```bash
pytest -q
```

The tests cover initial balance, buy/sell, insufficient funds, insufficient holdings, idempotency, precision behavior, feature calculations, signal normalization, backtest output, and the chronological ML pipeline.

## Known limitations

1. The build environment could not resolve external DNS, so live Binance connectivity and browser rendering could not be honestly verified from inside this sandbox. The code uses the documented Binance WebSocket/REST endpoints and fails closed when a fresh price is unavailable.
2. The UI is browser-native rather than Next.js because the environment's Node dependency installation timed out; the backend and analytical layers are independent and can be paired with a React/Next.js frontend later.
3. The simulator has one demo account and no authentication because the assignment is explicitly an educational local paper-trading system.
4. Backtests are single-asset, long/flat baselines and do not model order-book slippage beyond the configurable percentage fee.

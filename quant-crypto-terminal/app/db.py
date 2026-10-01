import sqlite3
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from .config import DB_PATH, INITIAL_CASH, SUPPORTED_ASSETS

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    cash_cents INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS holdings (
    account_id TEXT NOT NULL,
    asset TEXT NOT NULL,
    quantity_units INTEGER NOT NULL DEFAULT 0,
    avg_cost_microusd INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(account_id, asset),
    FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    client_order_id TEXT NOT NULL UNIQUE,
    asset TEXT NOT NULL,
    side TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
    quantity_units INTEGER NOT NULL,
    price_microusd INTEGER NOT NULL,
    notional_cents INTEGER NOT NULL,
    fee_cents INTEGER NOT NULL DEFAULT 0,
    realized_pnl_cents INTEGER NOT NULL DEFAULT 0,
    executed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_trades_account_time ON trades(account_id, executed_at DESC);
"""

# 1 BTC = 100,000,000 units; 1 USD = 100 cents; price stored in micro-USD.
Q_SCALE = Decimal("100000000")
P_SCALE = Decimal("1000000")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=10000")
    return con


def init_db() -> None:
    con = _connect()
    try:
        con.executescript(SCHEMA)
        row = con.execute("SELECT id FROM accounts WHERE id='demo'").fetchone()
        if not row:
            con.execute("INSERT INTO accounts(id, cash_cents) VALUES('demo', ?)", (int(INITIAL_CASH * 100),))
            for asset in SUPPORTED_ASSETS:
                con.execute("INSERT INTO holdings(account_id, asset) VALUES('demo', ?)", (asset,))
    finally:
        con.close()


def dec_to_units(q: Decimal) -> int:
    return int((q * Q_SCALE).to_integral_value())


def units_to_dec(u: int) -> Decimal:
    return Decimal(u) / Q_SCALE


def price_to_units(p: Decimal) -> int:
    return int((p * P_SCALE).to_integral_value())


def units_to_price(u: int) -> Decimal:
    return Decimal(u) / P_SCALE


def cents_to_dec(c: int) -> Decimal:
    return Decimal(c) / Decimal(100)


@contextmanager
def transaction():
    con = _connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        yield con
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def account_snapshot(account_id: str, prices: dict[str, Decimal]) -> dict:
    con = _connect()
    try:
        acct = con.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        if not acct:
            raise ValueError("Unknown account")
        hs = con.execute("SELECT * FROM holdings WHERE account_id=?", (account_id,)).fetchall()
        trades = con.execute("SELECT * FROM trades WHERE account_id=? ORDER BY id DESC LIMIT 50", (account_id,)).fetchall()
        cash = cents_to_dec(acct["cash_cents"])
        holdings = []
        invested = Decimal(0)
        for h in hs:
            qty = units_to_dec(h["quantity_units"])
            px = prices.get(h["asset"])
            value = qty * px if px is not None else Decimal(0)
            invested += value
            avg = units_to_price(h["avg_cost_microusd"])
            holdings.append({
                "asset": h["asset"], "quantity": str(qty), "avg_cost": str(avg),
                "price": str(px) if px is not None else None, "value": str(value),
            })
        total = cash + invested
        # Realized/unrealized are derived from ledger and current market state.
        realized = cents_to_dec(con.execute("SELECT COALESCE(SUM(realized_pnl_cents),0) FROM trades WHERE account_id=?", (account_id,)).fetchone()[0])
        unrealized = Decimal(0)
        for h in hs:
            px = prices.get(h["asset"])
            if px is not None:
                unrealized += (px - units_to_price(h["avg_cost_microusd"])) * units_to_dec(h["quantity_units"])
        return {
            "cash": str(cash), "invested": str(invested), "portfolio_value": str(total),
            "realized_pnl": str(realized), "unrealized_pnl": str(unrealized),
            "holdings": holdings,
            "trades": [dict(t) for t in trades],
        }
    finally:
        con.close()


def execute_trade(account_id: str, client_order_id: str, asset: str, side: str, qty: Decimal, price: Decimal, fee_rate: Decimal = Decimal("0")) -> dict:
    if asset not in SUPPORTED_ASSETS:
        raise ValueError("Unsupported asset")
    if side not in {"BUY", "SELL"}:
        raise ValueError("Side must be BUY or SELL")
    if qty <= 0:
        raise ValueError("Quantity must be > 0")
    if price <= 0 or not price.is_finite():
        raise ValueError("Invalid market price")

    q_units = dec_to_units(qty)
    if q_units <= 0:
        raise ValueError("Quantity below supported precision")
    p_units = price_to_units(price)
    # Compute notional with integer micro-USD * token units -> USD, then cents.
    notional = qty * price
    fee = (notional * fee_rate).quantize(Decimal("0.01"))
    total_buy = notional + fee
    cash_delta_cents = int((total_buy * 100).to_integral_value())

    with transaction() as con:
        # Idempotency first: a client retry gets the same trade.
        existing = con.execute("SELECT * FROM trades WHERE client_order_id=?", (client_order_id,)).fetchone()
        if existing:
            return {"status": "duplicate", "trade": dict(existing)}

        acct = con.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        if not acct:
            raise ValueError("Unknown account")
        hold = con.execute("SELECT * FROM holdings WHERE account_id=? AND asset=?", (account_id, asset)).fetchone()

        if side == "BUY":
            if acct["cash_cents"] < cash_delta_cents:
                raise ValueError("Insufficient funds")
            old_qty = units_to_dec(hold["quantity_units"])
            old_avg = units_to_price(hold["avg_cost_microusd"])
            new_qty = old_qty + qty
            new_avg = ((old_qty * old_avg) + (qty * price)) / new_qty if new_qty else Decimal(0)
            con.execute("UPDATE accounts SET cash_cents=cash_cents-? WHERE id=?", (cash_delta_cents, account_id))
            con.execute("UPDATE holdings SET quantity_units=?, avg_cost_microusd=? WHERE account_id=? AND asset=?",
                        (dec_to_units(new_qty), price_to_units(new_avg), account_id, asset))
            realized_cents = 0
        else:
            current_qty = units_to_dec(hold["quantity_units"])
            if current_qty < qty:
                raise ValueError("Insufficient holdings")
            proceeds = notional - fee
            proceeds_cents = int((proceeds * 100).to_integral_value())
            con.execute("UPDATE accounts SET cash_cents=cash_cents+? WHERE id=?", (proceeds_cents, account_id))
            avg = units_to_price(hold["avg_cost_microusd"])
            realized = ((price - avg) * qty - fee).quantize(Decimal("0.01"))
            realized_cents = int((realized * 100).to_integral_value())
            remaining = current_qty - qty
            con.execute("UPDATE holdings SET quantity_units=?, avg_cost_microusd=? WHERE account_id=? AND asset=?",
                        (dec_to_units(remaining), price_to_units(avg if remaining else Decimal(0)), account_id, asset))
            cash_delta_cents = -proceeds_cents

        con.execute("INSERT INTO trades(account_id, client_order_id, asset, side, quantity_units, price_microusd, notional_cents, fee_cents, realized_pnl_cents) VALUES(?,?,?,?,?,?,?,?,?)",
                    (account_id, client_order_id, asset, side, q_units, p_units,
                     int((notional * 100).to_integral_value()), int((fee * 100).to_integral_value()), realized_cents))
        trade = con.execute("SELECT * FROM trades WHERE client_order_id=?", (client_order_id,)).fetchone()
        return {"status": "executed", "trade": dict(trade), "cash_cents": acct["cash_cents"]}

import sqlite3
import os
from contextlib import contextmanager
from datetime import datetime

import yfinance as yf
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="Stock Tracker")

DB_PATH = os.path.join(os.path.dirname(__file__), "stocks.db")


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT UNIQUE NOT NULL,
                added_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def _get_stock_price(symbol: str) -> dict:
    """Fetch current price info for a stock symbol using yfinance."""
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.fast_info

        current_price = None
        previous_close = None

        if hasattr(info, 'previous_close') and info.previous_close:
            previous_close = info.previous_close
        if hasattr(info, 'last_price') and info.last_price:
            current_price = info.last_price
        elif hasattr(info, 'current_price') and info.current_price:
            current_price = info.current_price

        if current_price and previous_close:
            change = round(current_price - previous_close, 2)
            change_pct = round((change / previous_close) * 100, 2)
        else:
            change = None
            change_pct = None

        currency = None
        if hasattr(info, 'currency'):
            currency = info.currency

        market_state = "pre"
        if hasattr(info, 'market_state'):
            state_map = {
                "pre": "Pre-Market",
                "reg": "Regular",
                "post": "After Hours",
                "closed": "Closed",
            }
            raw_state = getattr(info, 'market_state', '')
            market_state = state_map.get(raw_state, raw_state) if raw_state else None

        return {
            "price": round(current_price, 2) if current_price else None,
            "change": change,
            "change_pct": change_pct,
            "currency": currency,
            "market_state": market_state,
            "last_updated": datetime.utcnow().isoformat(),
        }
    except Exception:
        return {
            "price": None,
            "change": None,
            "change_pct": None,
            "currency": None,
            "market_state": None,
            "last_updated": datetime.utcnow().isoformat(),
        }


class StockAdd(BaseModel):
    symbol: str


class StockPrice(BaseModel):
    symbol: str


class StockInfo(BaseModel):
    symbol: str
    price: float | None
    change: float | None
    change_pct: float | None
    currency: str | None
    market_state: str | None
    last_updated: str | None


@app.on_event("startup")
def startup():
    init_db()


@app.get("/stocks")
def list_stocks():
    with get_db() as conn:
        rows = conn.execute("SELECT symbol, added_at FROM stocks ORDER BY added_at DESC").fetchall()
        stocks = [dict(row) for row in rows]

    for stock in stocks:
        price_info = _get_stock_price(stock["symbol"])
        stock.update(price_info)

    return stocks


@app.get("/stocks/{symbol}/price")
def get_stock_price(symbol: str):
    symbol = symbol.upper().strip()
    price_info = _get_stock_price(symbol)
    return {"symbol": symbol, **price_info}


@app.post("/stocks")
def add_stock(stock: StockAdd):
    symbol = stock.symbol.upper().strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="Symbol cannot be empty")
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO stocks (symbol, added_at) VALUES (?, ?)",
                (symbol, datetime.utcnow().isoformat()),
            )
            conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail=f"Stock {symbol} already in watchlist")
    return {"symbol": symbol, "status": "added"}


@app.delete("/stocks/{symbol}")
def delete_stock(symbol: str):
    symbol = symbol.upper().strip()
    with get_db() as conn:
        result = conn.execute("DELETE FROM stocks WHERE symbol = ?", (symbol,))
        conn.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Stock {symbol} not found in watchlist")
    return {"symbol": symbol, "status": "deleted"}


@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(os.path.dirname(__file__), "templates", "index.html"), "r") as f:
        return f.read()

import sqlite3
import os
from contextlib import contextmanager
from datetime import datetime

import requests
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


# LM Studio configuration
LM_STUDIO_URL = os.getenv("LM_STUDIO_URL", "http://172.237.41.253:8000/v1")
LM_STUDIO_MODEL = os.getenv("LM_STUDIO_MODEL", "qwen/qwen3.6-35b-a3b")
LM_STUDIO_ENABLED = os.getenv("LM_STUDIO_ENABLED", "true").lower() in ("true", "1", "yes")


def _get_recommendations(stocks_data: list[dict]) -> str:
    """Send watchlist data to LM Studio for analysis."""
    if not LM_STUDIO_ENABLED:
        return "AI recommendations are disabled. Set LM_STUDIO_ENABLED=true to enable."

    # Build prompt with watchlist data
    prompt_lines = [
        "You are a stock market analyst. Analyze the following watchlist and provide brief buy/hold/sell recommendations.",
        "",
        "Watchlist data:",
    ]
    for stock in stocks_data:
        symbol = stock.get("symbol", "?")
        price = stock.get("price")
        change = stock.get("change")
        change_pct = stock.get("change_pct")
        market_state = stock.get("market_state")
        line = f"  - {symbol}"
        if price is not None:
            line += f"  Price: ${price}"
        if change is not None and change_pct is not None:
            line += f"  Change: {change:+.2f} ({change_pct:+.2f}%)"
        if market_state:
            line += f"  Market: {market_state}"
        prompt_lines.append(line)

    prompt_lines.extend([
        "",
        "RULES:",
        "1. Provide a recommendation for EACH stock in the watchlist.",
        "2. Use EXACTLY this format per stock:",
        "   [SYMBOL] → BUY / HOLD / SELL — [one short reason]",
        "3. BUY = price up > 2% or positive trend",
        "4. HOLD = price change between -2% and +2%",
        "5. SELL = price down > 2% or negative trend",
        "6. Be direct. No intro, no outro, no disclaimers.",
    ])

    system_prompt = (
        "You are a professional stock market analyst. "
        "Analyze price change data and give per-stock recommendations. "
        "Always output one line per stock. "
        "Never skip a stock. Never add commentary outside the recommendations."
    )

    try:
        response = requests.post(
            f"{LM_STUDIO_URL}/chat/completions",
            json={
                "model": LM_STUDIO_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "\n".join(prompt_lines)},
                ],
                "temperature": 0.5,
                "max_tokens": 1024,
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except requests.exceptions.ConnectionError:
        return "⚠️ Could not connect to LM Studio at " + LM_STUDIO_URL
    except Exception as e:
        return f"⚠️ Recommendations error: {e}"


class RecommendationResponse(BaseModel):
    symbol: str | None
    recommendation: str  # raw text from LLM or error message


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


@app.get("/recommendations")
def get_recommendations():
    """Get AI-powered buy/hold/sell recommendations for the watchlist."""
    with get_db() as conn:
        rows = conn.execute("SELECT symbol, added_at FROM stocks ORDER BY added_at DESC").fetchall()
        stocks = [dict(row) for row in rows]

    if not stocks:
        return {"recommendations": "Your watchlist is empty. Add some stocks first!"}

    # Fetch live price data for each stock
    stocks_data = []
    for stock in stocks:
        price_info = _get_stock_price(stock["symbol"])
        stock.update(price_info)
        stocks_data.append(stock)

    rec_text = _get_recommendations(stocks_data)
    return {"recommendations": rec_text}


@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(os.path.dirname(__file__), "templates", "index.html"), "r") as f:
        return f.read()

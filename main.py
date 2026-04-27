import sqlite3
import os
import re
import logging
import threading
import time
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import pandas as pd
import requests
import yfinance as yf
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

logger = logging.getLogger("stock_tracker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

app = FastAPI(title="Stock Tracker")

# Configuration
RECOMMENDATION_INTERVAL = int(os.getenv("RECOMMENDATION_INTERVAL", "900"))
RECOMMENDATIONS_ENABLED = os.getenv("RECOMMENDATIONS_ENABLED", "true").lower() in ("true", "1", "yes")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "60"))

# Global state
_last_recommendations = {}
_last_recommendations_full = []
_last_recommendations_ts = 0
_pending_alerts = []
_alerts_lock = threading.Lock()
_scheduler_task = None
_shutdown_event = threading.Event()

# Price cache with max size
_price_cache = {}
_price_cache_max = 100
_PRICE_CACHE_TTL = 30


def _recommendation_scheduler():
    """Periodically fetch AI recommendations and detect BUY/SELL signals (runs in background thread)."""
    global _last_recommendations, _last_recommendations_full, _last_recommendations_ts, _pending_alerts
    logger.info("Recommendation scheduler started (interval=%ds)", RECOMMENDATION_INTERVAL)
    while not _shutdown_event.is_set():
        _shutdown_event.wait(RECOMMENDATION_INTERVAL)
        if _shutdown_event.is_set():
            break
        try:
            with get_db() as conn:
                rows = conn.execute("SELECT symbol, added_at FROM stocks ORDER BY added_at DESC").fetchall()
                stocks = [dict(row) for row in rows]
            if not stocks:
                continue

            stocks_data = []
            for stock in stocks:
                price_info = _get_stock_price(stock["symbol"])
                stock.update(price_info)
                stocks_data.append(stock)

            rec_data = _get_recommendations(stocks_data)
            if isinstance(rec_data, str):
                logger.warning("Scheduler: %s", rec_data)
                continue

            _last_recommendations_full = rec_data
            _last_recommendations_ts = time.time()

            new_alerts = []
            for rec in rec_data:
                symbol = rec["symbol"]
                rec_type = rec["recommendation"]
                reason = rec["reason"]
                if rec_type in ("BUY", "SELL") and symbol not in _last_recommendations:
                    new_alerts.append({
                        "symbol": symbol,
                        "type": rec_type,
                        "reason": reason,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                _last_recommendations[symbol] = rec_type

            if new_alerts:
                with _alerts_lock:
                    _pending_alerts.extend(new_alerts)
                logger.info("Generated %d new alerts", len(new_alerts))
        except Exception as e:
            logger.error("Scheduler error: %s", e)
    logger.info("Recommendation scheduler stopped")

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


def _get_stock_price(symbol: str, use_cache: bool = True) -> dict:
    """Fetch current price info for a stock symbol using yfinance (with lightweight TTL cache)."""
    if use_cache:
        cached = _price_cache.get(symbol)
        if cached and (time.time() - cached["ts"]) < _PRICE_CACHE_TTL:
            return cached["data"]

    price_info = _fetch_stock_price_internal(symbol)
    if use_cache:
        # Enforce max cache size (evict oldest entry)
        if len(_price_cache) >= _price_cache_max:
            try:
                oldest = min(_price_cache, key=lambda k: _price_cache[k]["ts"])
                del _price_cache[oldest]
            except (ValueError, KeyError):
                pass
        _price_cache[symbol] = {"data": price_info, "ts": time.time()}
    return price_info


def _fetch_stock_price_internal(symbol: str) -> dict:
    """Internal yfinance fetch without cache logic."""
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

        market_state = None
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
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        return {
            "price": None,
            "change": None,
            "change_pct": None,
            "currency": None,
            "market_state": None,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }


class StockAdd(BaseModel):
    symbol: str


# Ollama configuration
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "deepseek-v4-flash:cloud")
OLLAMA_ENABLED = os.getenv("OLLAMA_ENABLED", "true").lower() in ("true", "1", "yes")


def _parse_recommendations(raw: str) -> list[dict]:
    """Parse LLM response into per-stock recommendation dict."""
    recommendations = []
    lines = raw.strip().split("\n")
    for line in lines:
        line = line.strip()
        if not line:
            continue
        match = re.match(r'(\w+)\s*[→>]\s*(BUY|HOLD|SELL)\s*—?\s*(.*)', line, re.IGNORECASE)
        if match:
            symbol = match.group(1).upper()
            rec = match.group(2).upper()
            reason = match.group(3).strip() or "Based on price trend"
            recommendations.append({
                "symbol": symbol,
                "recommendation": rec,
                "reason": reason,
            })
    return recommendations


def _get_recommendations(stocks_data: list[dict]) -> str:
    """Send watchlist data to Ollama for analysis and return parsed recommendations."""
    if not OLLAMA_ENABLED:
        return "AI recommendations are disabled. Set OLLAMA_ENABLED=true to enable."

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
        "7. Output one line per stock only.",
    ])

    system_prompt = (
        "You are a professional stock market analyst. "
        "Analyze price change data and give per-stock recommendations. "
        "Always output one line per stock. "
        "Never skip a stock. Never add commentary outside the recommendations."
    )

    try:
        response = requests.post(
            f"{OLLAMA_URL}/chat/completions",
            json={
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "\n".join(prompt_lines)},
                ],
                "temperature": 0.1,
                "max_tokens": 4096,
            },
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        raw = data["choices"][0]["message"]["content"]
        return _parse_recommendations(raw)
    except requests.exceptions.ConnectionError:
        return "⚠️ Could not connect to Ollama at " + OLLAMA_URL
    except Exception as e:
        return f"⚠️ Recommendations error: {e}"


@app.on_event("startup")
def startup():
    init_db()
    if RECOMMENDATIONS_ENABLED:
        global _scheduler_task
        _scheduler_task = threading.Thread(target=_recommendation_scheduler, daemon=True)
        _scheduler_task.start()
        logger.info("Startup complete")


@app.on_event("shutdown")
def shutdown():
    logger.info("Shutting down...")
    _shutdown_event.set()


@app.get("/health")
def health():
    """Health check endpoint."""
    db_ok = False
    try:
        with get_db() as conn:
            conn.execute("SELECT 1")
            db_ok = True
    except Exception:
        pass
    ollama_ok = False
    if OLLAMA_ENABLED:
        try:
            r = requests.get(f"{OLLAMA_URL}/models", timeout=5)
            ollama_ok = r.ok
        except Exception:
            pass
    return {
        "status": "ok" if db_ok else "degraded",
        "database": db_ok,
        "ollama": ollama_ok if OLLAMA_ENABLED else "disabled",
        "stocks_watched": _get_stock_count(),
    }


def _get_stock_count() -> int:
    try:
        with get_db() as conn:
            return conn.execute("SELECT COUNT(*) FROM stocks").fetchone()[0]
    except Exception:
        return 0


@app.get("/stocks")
def list_stocks(sort: str = "added_at"):
    with get_db() as conn:
        rows = conn.execute("SELECT symbol, added_at FROM stocks ORDER BY added_at DESC").fetchall()
        stocks = [dict(row) for row in rows]

    # Parallelize price fetching
    def fetch_price(s):
        s.update(_get_stock_price(s["symbol"]))
        return s

    with ThreadPoolExecutor(max_workers=10) as executor:
        stocks = list(executor.map(fetch_price, stocks))

    # Sort by requested field
    if sort == "price":
        stocks.sort(key=lambda s: s.get("price") or 0, reverse=True)
    elif sort == "change_pct":
        stocks.sort(key=lambda s: s.get("change_pct") or 0, reverse=True)
    elif sort == "symbol":
        stocks.sort(key=lambda s: s.get("symbol", ""))
    # else: keep default added_at order

    return stocks


@app.get("/stocks/{symbol}/history")
def get_stock_history(symbol: str, period: str = "1mo"):
    """Get historical price data for sparkline visualization."""
    symbol = symbol.upper().strip()
    period_map = {
        "1d": "1d",
        "5d": "5d",
        "1m": "1mo",
        "3m": "3mo",
        "6m": "6mo",
        "1y": "1y",
        "2y": "2y",
        "5y": "5y",
    }
    yf_period = period_map.get(period, "1mo")

    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=yf_period)
        if hist.empty:
            return {"symbol": symbol, "period": period, "data": []}

        points = []
        for date, row in hist.iterrows():
            points.append({
                "date": date.strftime("%Y-%m-%d"),
                "close": round(float(row["Close"]), 2),
                "volume": int(row["Volume"]) if not pd.isna(row["Volume"]) else 0,
            })
        return {"symbol": symbol, "period": period, "data": points}
    except Exception:
        return {"symbol": symbol, "period": period, "data": []}


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
                (symbol, datetime.now(timezone.utc).isoformat()),
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
    """Get AI-powered buy/hold/sell recommendations for the watchlist.
    Returns cached recommendations from the background scheduler if available,
    otherwise fetches fresh data synchronously."""
    global _last_recommendations_full, _last_recommendations_ts

    # Use cached recommendations if fresh (within 2x the recommendation interval)
    cache_age = time.time() - _last_recommendations_ts if _last_recommendations_ts else float('inf')
    if _last_recommendations_full and cache_age < RECOMMENDATION_INTERVAL * 2:
        return {"recommendations": _last_recommendations_full, "cached": True, "age_seconds": int(cache_age)}

    # Fall back to synchronous fetch if no cache
    with get_db() as conn:
        rows = conn.execute("SELECT symbol, added_at FROM stocks ORDER BY added_at DESC").fetchall()
        stocks = [dict(row) for row in rows]

    if not stocks:
        return {"recommendations": []}

    stocks_data = []
    for stock in stocks:
        price_info = _get_stock_price(stock["symbol"])
        stock.update(price_info)
        stocks_data.append(stock)

    rec_data = _get_recommendations(stocks_data)
    if isinstance(rec_data, str):
        return {"recommendations": [], "error": rec_data}

    # Update cache
    _last_recommendations_full = rec_data
    _last_recommendations_ts = time.time()

    return {"recommendations": rec_data, "cached": False}


@app.get("/alerts")
def get_alerts():
    """Get pending BUY/SELL alerts for the frontend."""
    with _alerts_lock:
        alerts = list(_pending_alerts)
        _pending_alerts.clear()
    return {"alerts": alerts}


@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(os.path.dirname(__file__), "templates", "index.html"), "r") as f:
        return f.read()

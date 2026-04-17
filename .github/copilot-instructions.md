# Stock Tracker - Copilot Instructions

## Project Overview
FastAPI application that tracks a stock watchlist. Fetches real-time prices via yfinance, stores symbols in SQLite, and serves a single-page HTML dashboard.

## Running the App
```bash
uvicorn main:app --reload
```

## Dependencies
```
fastapi[standard]
uvicorn>=0.30.0
yfinance>=0.2.40
```
Install with `pip install -r requirements.txt`.

## Architecture
- **`main.py`** - Entire application: FastAPI routes, SQLite logic, yfinance integration, Pydantic models
- **`templates/index.html`** - Single-page dashboard (vanilla JS, no framework)
- **`stocks.db`** - SQLite database with one table: `stocks(symbol, added_at)`
- **DB access** - Uses `get_db()` context manager; no ORM

## Key Conventions
- All stock symbols are normalized to uppercase via `.upper().strip()`
- `_get_stock_price()` is the single source of truth for fetching price data from yfinance (`ticker.fast_info`)
- The frontend uses `renderStocks()` to poll `/stocks` and display the watchlist with inline change coloring (green/red)
- `stocks.db` and `__pycache__/` are gitignored; do not commit data files

## Code Style
- Python 3.x, no type stubs beyond Pydantic models
- FastAPI route functions are top-level (no routers/organizational modules)
- Error handling: yfinance failures return `None` fields gracefully (not exceptions)

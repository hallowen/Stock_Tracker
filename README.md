# 📈 Stock Tracker

A real-time stock watchlist dashboard built with **FastAPI** and **yfinance**. Add symbols, track live prices with sparklines, and get AI-powered BUY/HOLD/SELL recommendations via **Ollama** — all from a sleek dark-themed glassmorphism UI.

---

## ⚡ Quick Start

```bash
git clone <repository-url> && cd Stock_Tracker
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
uvicorn main:app --reload
```

Open [http://localhost:8000](http://localhost:8000) 🚀

---

## 📦 Installation

| Requirement | Details |
|-------------|---------|
| **Python** | 3.10 or later |
| **Dependencies** | `fastapi[standard]`, `uvicorn`, `yfinance`, `requests`, `pandas` |

```bash
pip install -r requirements.txt
# or with uv:
uv pip install -r requirements.txt
```

---

## 🤖 AI Recommendations (Ollama)

The app uses a local LLM via **Ollama** for stock analysis. To enable:

1. Install [Ollama](https://ollama.com)
2. Pull a model: `ollama pull deepseek-v4-flash:cloud`
3. Ensure Ollama is running on `http://localhost:11434`
4. Click the 🤖 button in the app bar

**Environment variables:**

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_URL` | `http://localhost:11434/v1` | Ollama API endpoint |
| `OLLAMA_MODEL` | `deepseek-v4-flash:cloud` | Model name |
| `OLLAMA_ENABLED` | `true` | Enable/disable AI features |
| `OLLAMA_TIMEOUT` | `60` | Request timeout in seconds |
| `RECOMMENDATION_INTERVAL` | `900` | Background refresh interval (seconds) |
| `RECOMMENDATIONS_ENABLED` | `true` | Enable background scheduler |

---

## 🌐 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET`    | `/` | Serve the dashboard HTML |
| `GET`    | `/health` | Health check (DB + Ollama status) |
| `GET`    | `/stocks?sort=` | List watchlist with live prices (`added_at`, `price`, `change_pct`, `symbol`) |
| `POST`   | `/stocks` | Add a stock → `{"symbol": "AAPL"}` |
| `DELETE` | `/stocks/{symbol}` | Remove a stock |
| `GET`    | `/stocks/{symbol}/price` | Live price for a single stock |
| `GET`    | `/stocks/{symbol}/history?period=1mo` | Historical data for sparklines |
| `GET`    | `/recommendations` | AI-generated BUY/HOLD/SELL (cached) |
| `GET`    | `/alerts` | Pending BUY/SELL alerts (cleared on read) |

---

## 📂 Project Structure

```
Stock_Tracker/
├── .github/
│   └── copilot-instructions.md   # AI assistant guidelines
├── templates/
│   └── index.html                # SPA dashboard (vanilla JS)
├── main.py                       # FastAPI app — routes, DB, yfinance, Ollama
├── pyproject.toml                # Project metadata & dependencies
├── requirements.txt
├── stocks.db                     # SQLite (gitignored)
└── README.md
```

---

## 🧹 Key Features

- **Hyper-realistic UI** — Glassmorphism, animated orbs, glow effects, compact trading-terminal layout
- **Live prices** — yfinance integration with 30s TTL cache
- **Sparkline charts** — Canvas-rendered price history with gradient fills
- **Smooth price transitions** — Animated interpolation between refreshes
- **AI recommendations** — Background scheduler with cached results
- **BUY/SELL alerts** — Push notifications for signal changes
- **Parallel fetching** — Multi-threaded price updates for speed
- **Health endpoint** — Monitor DB and Ollama connectivity

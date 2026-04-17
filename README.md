# 📈 Stock Tracker

A real-time stock watchlist application built with **FastAPI** and **yfinance**. Add symbols, track live prices, and monitor market states — all from a sleek dark-themed dashboard.

---

## ⚡ Quick Start

```bash
git clone <repository-url> && cd Stock_Tracker
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Open [http://localhost:8000](http://localhost:8000) 🚀

---

## 📦 Installation

| Requirement | Details |
|-------------|---------|
| **Python** | 3.x or later |
| **Dependencies** | `fastapi[standard]`, `uvicorn>=0.30.0`, `yfinance>=0.2.40` |

```bash
pip install -r requirements.txt
```

---

## 🌐 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET`    | `/stocks?sort=added_at` | List all watched stocks with live prices (`sort` = `added_at`, `price`, `change_pct`, `symbol`) |
| `POST`   | `/stocks` | Add a stock → `{"symbol": "AAPL"}` |
| `DELETE` | `/stocks/{symbol}` | Remove a stock from watchlist |
| `GET`    | `/stocks/{symbol}/price` | Get live price for a single stock |
| `GET`    | `/stocks/{symbol}/history?period=1mo` | Get historical price data for sparkline visualization |
| `GET`    | `/stocks/recommendations` | Get AI-generated BUY/SELL/HOLD recommendations |
| `GET`    | `/alerts` | Get pending BUY/SELL alerts (cleared after read) |

---

## 📂 Project Structure

```
Stock_Tracker/
├── .github/
│   └── copilot-instructions.md   # AI assistant guidelines
├── templates/
│   └── index.html                # SPA dashboard (vanilla JS)
├── main.py                       # FastAPI app — routes, DB, yfinance
├── requirements.txt
├── stocks.db                     # SQLite (gitignored)
└── README.md
```

---

## 📝 License

MIT

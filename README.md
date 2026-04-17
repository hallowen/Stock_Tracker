# Stock Tracker

A stock watchlist application built with FastAPI. Track stock symbols and view real-time prices fetched via yfinance.

## Getting Started

### Prerequisites

- Python 3.x

### Installation

```bash
# Clone the repository
git clone <repository-url>
cd Stock_Tracker

# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Running the App

```bash
uvicorn main:app --reload
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/stocks` | List all watched stocks with live prices |
| `POST` | `/stocks` | Add a stock to the watchlist (body: `{"symbol": "AAPL"}`) |
| `DELETE` | `/stocks/{symbol}` | Remove a stock from the watchlist |
| `GET` | `/stocks/{symbol}/price` | Get live price for a single stock |

## Project Structure

```
Stock_Tracker/
├── .github/
│   └── copilot-instructions.md
├── templates/
│   └── index.html
├── main.py
├── requirements.txt
├── stocks.db
└── README.md
```

## License

MIT

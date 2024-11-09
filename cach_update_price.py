"""from fastapi import FastAPI
import ccxt
import time
from config import symbols_track_price
from function.create_redis_client import create_redis_client

app = FastAPI()
redis_client = create_redis_client()
binance_futures = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'future'}})

def update_prices():
    while True:
        try:
            tickers = binance_futures.fetch_tickers(symbols=symbols_track_price)
            for symbol, ticker in tickers.items():
                last_price = ticker.get('last')
                symbol = symbol.split(":")[0].replace("/", "")
                if last_price is not None:
                    redis_client.set(symbol, last_price)
                    print(f"Updated price for {symbol}: {last_price}")
                else:
                    print(f"No last price available for {symbol}")
        except Exception as e:
            print("Error fetching prices:", e)
        time.sleep(10)

@app.on_event("startup")
async def startup_event():
    await update_prices()

@app.get("/price/{symbol}")
async def get_price(symbol: str):
    price = redis_client.get(symbol)
    if price:
        return {"symbol": symbol, "price": float(price)}
    else:
        return {"symbol": symbol, "price": "N/A"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)"""
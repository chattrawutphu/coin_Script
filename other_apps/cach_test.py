from fastapi import FastAPI, BackgroundTasks
import ccxt
import time
import redis

app = FastAPI()
redis_client = redis.Redis(host='localhost', port=6379, db=0)
binance = ccxt.binance()

def update_prices():
    while True:
        try:
            tickers = binance.fetch_tickers()
            for symbol, ticker in tickers.items():
                redis_client.set(symbol, ticker['last'])
        except Exception as e:
            print("Error fetching prices:", e)
        time.sleep(5)

@app.on_event("startup")
async def startup_event(background_tasks: BackgroundTasks):
    background_tasks.add_task(update_prices)

@app.get("/price/{symbol}")
async def get_price(symbol: str):
    price = redis_client.get(symbol)
    if price:
        return {"symbol": symbol, "price": float(price)}
    else:
        return {"symbol": symbol, "price": "N/A"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

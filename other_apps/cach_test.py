from fastapi import FastAPI, BackgroundTasks
import ccxt
import time
import redis

app = FastAPI()
redis_client = redis.Redis(
    host='redis-16692.c84.us-east-1-2.ec2.redns.redis-cloud.com',
    port=16692,
    password='esnR4WeNvSGUvlygaLlBQvdSA19u05to'
)
binance_futures = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'future'}})

symbols_to_track = ['BTC/USDT', 'ETH/USDT']

def update_prices():
    while True:
        try:
            tickers = binance_futures.fetch_tickers(symbols=symbols_to_track)
            for symbol, ticker in tickers.items():
                last_price = ticker.get('last')
                if last_price is not None:
                    redis_client.set(symbol, last_price)
                    print(f"Updated price for {symbol}: {last_price}")
                else:
                    print(f"No last price available for {symbol}")
        except Exception as e:
            print("Error fetching prices:", e)
        time.sleep(5)

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
    uvicorn.run(app, host="0.0.0.0", port=8000)
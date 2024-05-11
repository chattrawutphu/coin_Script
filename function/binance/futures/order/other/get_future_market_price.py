import ccxt.async_support as ccxt
from function.binance.futures.system.create_future_exchange import create_future_exchange
from config import symbols_track_price
from function.create_redis_client import create_redis_client

async def get_future_market_price(api_key, api_secret, symbol):

    try:
        if symbol in symbols_track_price:
            redis_client = create_redis_client()
            price = redis_client.get(symbol)
            return float(price)
        else:
            exchange = await create_future_exchange(api_key, api_secret)
            ticker = await exchange.fetch_ticker(symbol)
            market_price = float(ticker['last'])

            await exchange.close()
            return market_price
    except Exception as e:
        print(f"Error: {e}")
        return None
import traceback
import ccxt.async_support as ccxt
from config import default_testnet as testnet
from funtion.binance.futures.system.create_future_exchange import create_future_exchange

async def get_top_candle_price(api_key, api_secret, symbol, num_candles, candle_type, timeframe='4h'):
    try:
        exchange = await create_future_exchange(api_key, api_secret)

        exchange.set_sandbox_mode(testnet)

        candles = await exchange.fetch_ohlcv(symbol, timeframe)

        relevant_candles = candles[-num_candles:]

        max_high = max([candle[2] for candle in relevant_candles])

        await exchange.close()

        return max_high

    except Exception as e:
        print(f"Error in get_top_candle_price: {str(e)}")
        await exchange.close()
        return None

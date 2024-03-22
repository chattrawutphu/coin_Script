import traceback
import ccxt.async_support as ccxt
from config import default_testnet as testnet

async def get_top_candle_price(api_key, api_secret, symbol, num_candles, candle_type, timeframe='4h'):
    try:
        exchange = ccxt.binance({
            'apiKey': api_key,
            'secret': api_secret,
            'enableRateLimit': True,
            'options': {'defaultType': 'future'},
        })

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

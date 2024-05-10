import ccxt.async_support as ccxt
import traceback

from function.binance.futures.system.create_future_exchange import create_future_exchange

async def check_user_api_status(api_key, api_secret):
    exchange = await create_future_exchange(api_key, api_secret)

    try:
        await exchange.fetch_balance()
        await exchange.close()
        return True
    except ccxt.BaseError as e:
        return False
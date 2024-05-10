import ccxt.async_support as ccxt

from funtion.binance.futures.system.create_future_exchange import create_future_exchange

async def check_server_status(api_key, api_secret):
    exchange = await create_future_exchange(api_key, api_secret)

    try:
        response = exchange.fetch_status()
        # status = response['status']
        # updated_time = exchange.iso8601(response['updated'])
        await exchange.close()
        return True
    except ccxt.BaseError as e:
        return False
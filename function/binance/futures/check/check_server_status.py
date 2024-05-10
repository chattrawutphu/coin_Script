import ccxt.async_support as ccxt

from function.binance.futures.system.create_future_exchange import create_future_exchange

async def check_server_status(api_key, api_secret):
    exchange = await create_future_exchange(api_key, api_secret, testnet=False)

    try:
        await exchange.fetch_status()
        await exchange.close()
        return True
    except ccxt.BaseError as e:
        return False
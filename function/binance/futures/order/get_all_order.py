import ccxt.async_support as ccxt
from config import default_testnet as testnet
from function.binance.futures.system.create_future_exchange import create_future_exchange

async def get_all_order(api_key, api_secret, symbol=None):
    exchange = await create_future_exchange(api_key, api_secret, warnOnFetchOpenOrdersWithoutSymbol=False)

    orders = await exchange.fetch_open_orders(symbol)
    await exchange.close()
    return orders


import ccxt.async_support as ccxt
from config import default_testnet as testnet

async def create_future_exchange(api_key, api_secret,warnOnFetchOpenOrdersWithoutSymbol=True):
    exchange = ccxt.binance({
        'apiKey': api_key,
        'secret': api_secret,
        'enableRateLimit': True,
        'options': {
            'defaultType': 'future',
            'adjustForTimeDifference': True,
            'warnOnFetchOpenOrdersWithoutSymbol': warnOnFetchOpenOrdersWithoutSymbol,
            #'hedgeMode': True
        }
    })

    exchange.set_sandbox_mode(testnet)

    # await exchange.load_markets()
    return exchange
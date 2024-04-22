import ccxt.async_support as ccxt
from config import default_testnet
from funtion.binance.futures.system.create_future_exchange import create_future_exchange

async def get_future_available_balance(api_key, api_secret, testnet = default_testnet):
    exchange = await create_future_exchange(api_key, api_secret)

    try:
        balance = await exchange.fetch_balance()
        future_balance = balance['info']['availableBalance']
        await exchange.close()
        return future_balance
    
    except ccxt.NetworkError as e:
        print('Network error:', e)
    except ccxt.ExchangeError as e:
        print('Exchange error:', e)
    except Exception as e:
        print('Error:', e)
    return None

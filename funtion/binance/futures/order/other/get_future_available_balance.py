import ccxt.async_support as ccxt
from config import default_testnet

async def get_future_available_balance(api_key, api_secret, testnet = default_testnet):
    exchange = ccxt.binance({
        'apiKey': api_key,
        'secret': api_secret,
        'enableRateLimit': True,
        'options': {
            'defaultType': 'future',
        },
    })
    exchange.set_sandbox_mode(testnet)

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

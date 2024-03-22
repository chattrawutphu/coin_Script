import ccxt.async_support as ccxt
from config import default_testnet as testnet

async def get_future_market_price(api_key, api_secret, symbol):
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
        # เรียกใช้งาน API ของตลาดสินค้าปัจจุบัน
        ticker = await exchange.fetch_ticker(symbol)
        market_price = float(ticker['last'])  # ใช้ 'last' เพื่อรับราคาล่าสุด

        await exchange.close()
        return market_price
        

    except ccxt.NetworkError as e:
        print('Network error:', e)
    except ccxt.ExchangeError as e:
        print('Exchange error:', e)
    except Exception as e:
        print('Error:', e)
    return None
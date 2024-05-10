import ccxt.async_support as ccxt
from config import default_testnet as testnet
from function.binance.futures.system.create_future_exchange import create_future_exchange

async def get_future_market_price(api_key, api_secret, symbol):
    exchange = await create_future_exchange(api_key, api_secret)

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
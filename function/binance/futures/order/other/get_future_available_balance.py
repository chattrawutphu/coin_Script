import traceback
import ccxt.async_support as ccxt
from config import default_testnet
from function.binance.futures.system.create_future_exchange import create_future_exchange
from function.message import message

async def get_future_available_balance(api_key, api_secret):
    exchange = await create_future_exchange(api_key, api_secret)

    try:
        balance = await exchange.fetch_balance()
        future_balance = balance['info']['availableBalance']
        await exchange.close()
        return future_balance
    
    except Exception as e:
        error_traceback = traceback.format_exc()
        message("พบข้อผิดพลาด", "yellow")
        print(f"Error: {error_traceback}")
    return None

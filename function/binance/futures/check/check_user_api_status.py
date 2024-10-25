import ccxt.async_support as ccxt
import traceback

from function.binance.futures.system.create_future_exchange import create_future_exchange

async def check_user_api_status(api_key: str, api_secret: str):
    """ตรวจสอบความถูกต้องของ API key และ secret"""
    exchange = None
    try:
        exchange = await create_future_exchange(api_key, api_secret)
        await exchange.fetch_balance()
        return True
    except ccxt.AuthenticationError:
        return False
    except Exception:
        return False
    finally:
        if exchange:
            await exchange.close()
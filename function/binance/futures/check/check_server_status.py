import ccxt.async_support as ccxt

from function.binance.futures.system.create_future_exchange import create_future_exchange

async def check_server_status(api_key: str, api_secret: str):
    """ตรวจสอบสถานะการเชื่อมต่อกับเซิร์ฟเวอร์ Binance"""
    exchange = None
    try:
        exchange = await create_future_exchange(api_key, api_secret, testnet=False)
        status = await exchange.fetch_status()
        return status.get('status') == 'ok'
    except Exception:
        return False
    finally:
        if exchange:
            await exchange.close()
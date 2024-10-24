import time
import traceback
import ccxt.async_support as ccxt
from config import default_testnet
from function.binance.futures.system.retry_utils import retry_with_backoff
from function.message import message

# Context manager สำหรับจัดการ exchange
from contextlib import asynccontextmanager

@asynccontextmanager
async def get_exchange_context(api_key, api_secret, warnOnFetchOpenOrdersWithoutSymbol=True, testnet=default_testnet):
   exchange = None
   try:
       exchange = await create_future_exchange(api_key, api_secret, warnOnFetchOpenOrdersWithoutSymbol, testnet)
       yield exchange
   finally:
       if exchange:
           try:
               await exchange.close()
           except:
               pass

@retry_with_backoff(max_retries=3)
async def create_future_exchange(api_key, api_secret, warnOnFetchOpenOrdersWithoutSymbol=True, testnet=default_testnet):
   try:
       exchange = ccxt.binance({
           'apiKey': api_key,
           'secret': api_secret,
           'enableRateLimit': True,
           'options': {
               'defaultType': 'future',
               'warnOnFetchOpenOrdersWithoutSymbol': warnOnFetchOpenOrdersWithoutSymbol,
               'createMarketBuyOrderRequiresPrice': False,
               'fetchTickersMethod': 'publicGetTickerPrice',
               'recvWindow': 60000,  # เพิ่มเวลารอการตอบกลับ
               'loadMarkets': False,  # ลดการโหลดข้อมูลที่ไม่จำเป็น
               'fetchCurrencies': False,
           },
           'timeout': 30000,  # เพิ่มเวลา timeout
       })

       exchange.set_sandbox_mode(testnet)

       # สร้าง nonce function ใหม่ที่ใช้เวลาจาก Binance
       exchange.nonce = lambda: int(time.time() * 1000) - 500  # ลบออก 500ms เพื่อป้องกัน

       return exchange
       
   except Exception as e:
       error_traceback = traceback.format_exc()
       message('', f"เกิดข้อผิดพลาดเมื่อเชื่อม exchange: {str(e)}", "red")
       message('', "________________________________", "red")
       print(f"Error: {error_traceback}")
       message('', "________________________________", "red")
       raise e
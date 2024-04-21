import asyncio
import json
import traceback

import ccxt
import config
from config import default_testnet as testnet
from funtion.binance.futures.order.create_tpsl import create_tpsl
from funtion.binance.futures.order.create_order import create_order
from funtion.message import message
from funtion.binance.futures.order.other.get_adjust_precision_price import get_adjust_precision_price
from funtion.binance.futures.order.other.get_future_available_balance import get_future_available_balance
from funtion.binance.futures.order.other.get_reduce_lastdecimal import get_reduce_lastdecimal
from funtion.binance.futures.order.other.get_future_market_price import get_future_market_price


# api_key = "yRMHGar6ENAMDJ6w8vqWlU2p8d1sMQCIdBNx7nlqsUBlsqnTZr17aL7nSSv8CdEy"
# api_secret = "oQUTD1bYBj8Uy7GUJzWBnDuOSMckS6QxOogj0PpryNHLvKj0iakx2LoOjwFJKp6v"

api_key = '6041331240427dbbf26bd671beee93f6686b57dde4bde5108672963fad02bf2e'
api_secret = '560764a399e23e9bc5e24d041bd3b085ee710bf08755d26ff4822bfd9393b11e'

async def main():

    # future_balance_1 = get_future_available_balance(api_key=api_key, api_secret=api_secret)
    # future_balance_2 = get_future_available_balance(api_key='yRMHGar6ENAMDJ6w8vqWlU2p8d1sMQCIdBNx7nlqsUBlsqnTZr17aL7nSSv8CdEy', api_secret='oQUTD1bYBj8Uy7GUJzWBnDuOSMckS6QxOogj0PpryNHLvKj0iakx2LoOjwFJKp6v', testnet=False)
    # future_balance_3 = get_future_available_balance(api_key=api_key, api_secret=api_secret)
    # future_balance_4 = get_future_available_balance(api_key=api_key, api_secret=api_secret)

    # future_balances = await asyncio.gather(future_balance_1, future_balance_2, future_balance_3, future_balance_4)

    # print(f"Future balance 1: {future_balances[0]}")
    # print(f"Future balance 2: {future_balances[1]}")
    # print(f"Future balance 3: {future_balances[2]}")
    # print(f"Future balance 4: {future_balances[3]}")

    try:
        # price = await get_future_market_price(api_key, api_secret, symbol=symbol)
        # print(f"{symbol}: {price}")

        # price = get_adjust_precision_price(symbol=symbol, price=price)
        # print(f"{symbol}: {price}")

        # price = get_reduce_lastdecimal(symbol=symbol, price=price, reduce_amount=-2)
        # print(f"{symbol}: {price}")

        #order = await create_order(api_key, api_secret, symbol='BTCUSDT', side='sell', price='now', quantity='500$', order_type='market')

        #order = await create_order(api_key, api_secret, symbol='BTCUSDT', side='buy', price='40000', quantity='500$', order_type='limit')
        #order = await create_order(api_key, api_secret, symbol='BTCUSDT', side='buy', price='50000', quantity='500$', order_type='stop_market')

        #order = await create_order(api_key, api_secret, symbol='BTCUSDT', side='buy', price='5%', quantity='500$', order_type='stop_market')
        #order = await create_order(api_key, api_secret, symbol='BTCUSDT', side='buy', price='5%', quantity='500$', order_type='limit')
        #order = await create_order(api_key, api_secret, symbol='BTCUSDT', side='buy', price='5%', quantity='500$', order_type='stop_limit', stop_price='-0.1_lastint_from_price')

        # lastint คือ เอาราคาปัจจุบัน + หรือ - ด้วยเลขด้านหน้าตามจำนวนเต็ม เช่น ใช้คำสั่ง stop market 5000_lastint ขณะที่ btc = 50000.00 จะสร้าง order ที่ btc 55000.00
        # lastdecimal เอาราคาปัจจุบัน + หรือ - ด้วยเลขด้านหน้าตามจทศนิยมหลังสุด เช่น ใช้คำสั่ง stop market 5000_lastdecimal ขณะที่ btc = 50000.00 จะสร้าง order ที่ btc 50050.00
        # _candle จะเอาราคาแท่งเทียนตามเงื่อนไขที่เลือก
        
        #order = await create_order(api_key, api_secret, symbol='BTCUSDT', side='buy', price='5000_lastint', quantity='500$', order_type='stop_limit', stop_price='-2500_lastint_from_price')
        #order = await create_order(api_key, api_secret, symbol='BTCUSDT', side='buy', price='1000_lastdecimal/1d/100_top_hight_candle', quantity='500$', order_type='stop_market')
        #order = await create_order(api_key, api_secret, symbol='BTCUSDT', side='buy', price='55000', quantity='500$', order_type='stop_limit', stop_price='1000_lastdecimal/1d/100_top_hight_candle')
        
        #order = await create_tpsl(api_key, api_secret, symbol='BTCUSDT', side='buy', price='70000', quantity='500$', order_type='STOP')
        
        #order = await create_order(api_key, api_secret, symbol='BTCUSDT', side='sell', price='now', quantity='500$', order_type='market')
        order = await create_order(api_key, api_secret, symbol='BTCUSDT', side='buy', price='20000', quantity='500$', order_type='limit')
        print(f"{order}")
        
    except Exception as e:
        error_traceback = traceback.format_exc()
        message(f"พบข้อผิดพลาด","yellow")
        print(f"Error: {error_traceback}")

if __name__ == "__main__":
    asyncio.run(main())


# order = get_futures_account_info(api_key, api_secret)
# print(order)

# order = create_order(api_key, api_secret, 'BTCUSDT', '50%', 'BUY', 'limit', '5%')
# print(order)
# order = create_order(api_key, api_secret, 'BTCUSDT', '50%', 'sell', 'stop_market', '5%')
# print(order)

# order = create_stop_loss(api_key, api_secret, 'BTCUSDT', '5%', 'stop_market', '2')
# print(order)
import asyncio
import json
import traceback

import ccxt
import config
from config import default_testnet as testnet
from function.binance.futures.check.check_future_available_balance import check_future_available_balance
from function.binance.futures.check.check_position import check_position
from function.binance.futures.check.check_price import check_price
from function.binance.futures.check.check_server_status import check_server_status
from function.binance.futures.check.check_user_api_status import check_user_api_status
from function.binance.futures.order.create_order import create_order
from function.binance.futures.order.get_all_order import get_all_order
from function.codelog import codelog
from function.message import message
from function.server_logs import save_server_logs


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

        # lastint คือ เอาราคาปัจจุบัน + หรือ - ด้วยเลขด้านหน้าตามจำนวนเต็ม เช่น ใช้คำสั่ง stop market -5000_lastint ขณะที่ btc = 50000.00 จะสร้าง order ที่ btc 45000.00
        # lastdecimal เอาราคาปัจจุบัน + หรือ - ด้วยเลขด้านหน้าตามจทศนิยมหลังสุด เช่น ใช้คำสั่ง stop market 5000_lastdecimal ขณะที่ btc = 50000.00 จะสร้าง order ที่ btc 50050.00
        # _candle จะเอาราคาแท่งเทียนตามเงื่อนไขที่เลือก

        #order = await create_order(api_key, api_secret, symbol='BTCUSDT', side='buy', price='5000_lastint', quantity='500$', order_type='stop_limit', stop_price='-2500_lastint_from_price')
        #order = await create_order(api_key, api_secret, symbol='BTCUSDT', side='buy', price='1000_lastdecimal/1d/100_top_hight_candle', quantity='500$', order_type='stop_market')
        #order = await create_order(api_key, api_secret, symbol='BTCUSDT', side='buy', price='55000', quantity='500$', order_type='stop_limit', stop_price='1000_lastdecimal/1d/100_top_hight_candle')
        
        #order = await create_tpsl(api_key, api_secret, symbol='BTCUSDT', side='buy', price='70000', quantity='500$', order_type='STOP')
        
        #order = await create_order(api_key, api_secret, symbol='BTCUSDT', side='sell', price='now', quantity='500$', order_type='market')
        
        # TAKE_PROFIT_MARKET buy ใช้สำหรับปิด short position และราคาต้องต่ำกว่า market

        try:
            if await check_server_status(api_key, api_secret):
                codelog(api_key, api_secret, "s1001t")
                if await check_user_api_status(api_key, api_secret):
                    codelog(api_key, api_secret, "s1002t")
                    if await check_price(api_key, api_secret, 'BTCUSDT', '80000', '<=', condition_price="add/10_lastint/1h"):
                        codelog(api_key, api_secret, "c1001t", param1='BTCUSDT', param2='80000', param3='<=')
                        if await check_future_available_balance(api_key, api_secret, '500', '>='):
                            codelog(api_key, api_secret, "c1002t", param1='500', param2='>=')
                            if await check_position(api_key, api_secret, 'BTCUSDT'):
                                codelog(api_key, api_secret, "c1003t", param1='BTCUSDT')
                                #order = await create_order(api_key, api_secret, symbol='BTCUSDT', side='buy', price='58000', quantity='500$', order_type='limit')
                                ##order = await create_order(api_key, api_secret, symbol='BTCUSDT', side='buy', price='now', quantity='500$', order_type='market')
                                #order = await create_order(api_key, api_secret, symbol='BTCUSDT', side='sell', price='-10%', quantity='50%', order_type='STOPLOSS_MARKET')
                                #order = await create_order(api_key, api_secret, symbol='BTCUSDT', side='sell', price='-20%', quantity='50%', order_type='STOPLOSS_MARKET')
                                #order = await create_order(api_key, api_secret, symbol='BTCUSDT', side='sell', price='10%', quantity='100%', order_type='TAKE_PROFIT_MARKET')
                                await save_order_history(api_key, api_secret, order)
                                await cancle_order(api_key, api_secret, symbol='BTCUSDT')
                                await cancle_position(api_key, api_secret, symbol='BTCUSDT')

                                await cancle_all_order(api_key, api_secret)
                                await cancle_all_position(api_key, api_secret)
                            else:
                                codelog(api_key, api_secret, "c1003f", param1='BTCUSDT')
                        else:
                            codelog(api_key, api_secret, "c1002f", param1='500', param2='>=')
                    else:
                        codelog(api_key, api_secret, "c1001f", param1='BTCUSDT', param2='80000', param3='<=')
                else:
                    codelog(api_key, api_secret, "s1002f")
            else:
                codelog(api_key, api_secret, "s1001f")

        except ccxt.NetworkError as e:
            error_traceback = traceback.format_exc()
            print(f'Network error occurred: {error_traceback}')
        except ccxt.ExchangeError as e:
            error_traceback = traceback.format_exc()
            print(f'Exchange error occurred: {error_traceback}')
        except ccxt.BaseError as e:
            error_traceback = traceback.format_exc()
            print(f'CCXT Base error occurred: {error_traceback}')
        except Exception as e:
            error_traceback = traceback.format_exc()
            print(f'An unexpected error occurred: {error_traceback}')
        finally:
            pass
        # orders = await get_all_order(api_key, api_secret)
        
        
    except Exception as e:
        error_traceback = traceback.format_exc()
        message(f"พบข้อผิดพลาด","yellow")
        message(symbol, f"Error: {error_traceback}", "red")

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
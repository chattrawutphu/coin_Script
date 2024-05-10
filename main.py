import asyncio
import json
import traceback

from function.binance.futures.check.check_future_available_balance import check_future_available_balance
from function.binance.futures.check.check_position import check_position
from function.binance.futures.check.check_price import check_price
from function.binance.futures.check.check_server_status import check_server_status
from function.binance.futures.check.check_user_api_status import check_user_api_status
from function.binance.futures.order.create_order import create_order
from function.binance.futures.order.get_all_order import get_all_order
from function.codelog import codelog
from function.message import message

api_key = '6041331240427dbbf26bd671beee93f6686b57dde4bde5108672963fad02bf2e'
api_secret = '560764a399e23e9bc5e24d041bd3b085ee710bf08755d26ff4822bfd9393b11e'

async def main():

    try:
        if await check_server_status(api_key, api_secret):
            await codelog(api_key, api_secret, "s1001t")
            if await check_user_api_status(api_key, api_secret):
                await codelog(api_key, api_secret, "s1002t")
                if await check_price(api_key, api_secret, 'BTCUSDT', '80000', '<=', condition_price="add/10_lastint/1h"):
                    await codelog(api_key, api_secret, "c1001t", param1='BTCUSDT', param2='80000', param3='<=')
                    if await check_future_available_balance(api_key, api_secret, '500', '>='):
                        await codelog(api_key, api_secret, "c1002t", param1='500', param2='>=')
                        if await check_position(api_key, api_secret, 'BTCUSDT') == False:
                            await codelog(api_key, api_secret, "c1003t", param1='BTCUSDT')
                            
                            order = await create_order(api_key, api_secret, symbol='BTCUSDT', side='buy', price='40000', quantity='500$', order_type='limit')
                            if order != None:
                                #await save_order(api_key, api_secret, order)
                                await codelog(api_key, api_secret, "a1001t", param1='BTCUSDT', param2='buy', param3='40000', param4='500$', param5='llimit')

                            ##order = await create_order(api_key, api_secret, symbol='BTCUSDT', side='buy', price='now', quantity='500$', order_type='market')
                            #order = await create_order(api_key, api_secret, symbol='BTCUSDT', side='sell', price='-10%', quantity='50%', order_type='STOPLOSS_MARKET')
                            #order = await create_order(api_key, api_secret, symbol='BTCUSDT', side='sell', price='-20%', quantity='50%', order_type='STOPLOSS_MARKET')
                            #order = await create_order(api_key, api_secret, symbol='BTCUSDT', side='sell', price='10%', quantity='100%', order_type='TAKE_PROFIT_MARKET')
                            
                            # await save_order_history(api_key, api_secret, order)
                            # await cancle_order(api_key, api_secret, symbol='BTCUSDT')
                            # await cancle_position(api_key, api_secret, symbol='BTCUSDT')

                            # await cancle_all_order(api_key, api_secret)
                            # await cancle_all_position(api_key, api_secret)
                        else:
                            await codelog(api_key, api_secret, "c1003f", param1='BTCUSDT')
                    else:
                        await codelog(api_key, api_secret, "c1002f", param1='500', param2='>=')
                else:
                    await codelog(api_key, api_secret, "c1001f", param1='BTCUSDT', param2='80000', param3='<=')
            else:
                await codelog(api_key, api_secret, "s1002f")
        else:
            await codelog(api_key, api_secret, "s1001f")
        
    except Exception as e:
        error_traceback = traceback.format_exc()
        message(f"พบข้อผิดพลาด","yellow")
        print(f"Error: {error_traceback}")

if __name__ == "__main__":
    asyncio.run(main())
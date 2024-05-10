import traceback
import ccxt.async_support as ccxt
from function.binance.futures.system.create_future_exchange import create_future_exchange
from function.message import message

async def check_price(api_key, api_secret, symbol, price, operator, condition_price=None):

    exchange = await create_future_exchange(api_key, api_secret)

    try:
        ticker = await exchange.fetch_ticker(symbol)
        await exchange.close()

        if operator == '>':
            return ticker['last'] > float(price)
        elif operator == '>=':
            return ticker['last'] >= float(price)
        elif operator == '<':
            return ticker['last'] < float(price)
        elif operator == '<=':
            return ticker['last'] <= float(price)
        elif operator == '=' or operator == '==':
            return ticker['last'] == float(price)
        elif operator == '!=':
            return ticker['last'] != float(price)
        else:
            raise ValueError('Operator ไม่ถูกต้อง')
    except Exception as e:
        error_traceback = traceback.format_exc()
        message(f"พบข้อผิดพลาด","yellow")
        print(f"Error: {error_traceback}")
        return False
import traceback
import ccxt.async_support as ccxt
from function.binance.futures.order.other.get_future_market_price import get_future_market_price
from function.binance.futures.system.create_future_exchange import create_future_exchange
from function.message import message

async def check_price(api_key, api_secret, symbol, price, operator, condition_price=None):

    exchange = await create_future_exchange(api_key, api_secret)

    try:
        ticker_price = get_future_market_price(api_key, api_secret, symbol)
        await exchange.close()

        if operator == '>':
            return ticker_price > float(price)
        elif operator == '>=':
            return ticker_price >= float(price)
        elif operator == '<':
            return ticker_price < float(price)
        elif operator == '<=':
            return ticker_price <= float(price)
        elif operator == '=' or operator == '==':
            return ticker_price == float(price)
        elif operator == '!=':
            return ticker_price != float(price)
        else:
            raise ValueError('Operator ไม่ถูกต้อง')
    except Exception as e:
        error_traceback = traceback.format_exc()
        message(f"พบข้อผิดพลาด","yellow")
        print(f"Error: {error_traceback}")
        return False
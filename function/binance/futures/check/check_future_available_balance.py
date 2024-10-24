import traceback
import ccxt.async_support as ccxt
from function.binance.futures.order.other.get_future_available_balance import get_future_available_balance
from function.binance.futures.system.create_future_exchange import create_future_exchange
from function.message import message

async def check_future_available_balance(api_key, api_secret, balance, operator, condition_price=None):

    exchange = await create_future_exchange(api_key, api_secret)

    try:
        avaliable_balance = float(await get_future_available_balance(api_key, api_secret))
        await exchange.close()

        if operator == '>':
            return avaliable_balance > float(balance)
        elif operator == '>=':
            return avaliable_balance >= float(balance)
        elif operator == '<':
            return avaliable_balance < float(balance)
        elif operator == '<=':
            return avaliable_balance <= float(balance)
        elif operator == '=' or operator == '==':
            return avaliable_balance == float(balance)
        elif operator == '!=':
            return avaliable_balance != float(balance)
        else:
            raise ValueError('Operator ไม่ถูกต้อง')
    except Exception as e:
        error_traceback = traceback.format_exc()
        message(f"พบข้อผิดพลาด","yellow")
        message(symbol, f"Error: {error_traceback}", "red")
        return False
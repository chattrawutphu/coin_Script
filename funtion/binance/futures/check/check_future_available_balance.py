import ccxt.async_support as ccxt
from funtion.binance.futures.order.other.get_future_available_balance import get_future_available_balance
from funtion.binance.futures.system.create_future_exchange import create_future_exchange

async def check_future_available_balance(api_key, api_secret, balance, operator, condition_price=None):

    exchange = await create_future_exchange(api_key, api_secret)
    avaliable_balance = await get_future_available_balance(api_key, api_secret)
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
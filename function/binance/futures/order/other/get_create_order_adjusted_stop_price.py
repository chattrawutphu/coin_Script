from function.binance.futures.order.other.get_adjust_precision_price import get_adjust_precision_price
from function.binance.futures.order.other.get_reduce_lastdecimal import get_reduce_lastdecimal
from function.binance.futures.order.other.get_top_candle_price import get_top_candle_price

async def get_adjusted_stop_price(api_key, api_secret, price, stop_price, latest_price, side, symbol):
    if stop_price.endswith('%'):
        stop_price = latest_price + ((latest_price * float(stop_price.strip('%'))) / 100)
    elif stop_price.endswith('%_from_price'):
        stop_price = price + ((latest_price * float(stop_price.strip('%_from_price'))) / 100)
    elif stop_price.endswith('_lastdecimal'):
        stop_price = get_reduce_lastdecimal(symbol, latest_price, stop_price.strip('_lastdecimal'))
    elif stop_price.endswith('_lastdecimal_from_price'):
        stop_price = get_reduce_lastdecimal(symbol, price, stop_price.strip('_lastdecimal_from_price'))
    elif stop_price.endswith('_lastint'):
        stop_price = latest_price + float(stop_price.strip('_lastint'))
    elif stop_price.endswith('_lastint_from_price'):
        stop_price = price + float(stop_price.strip('_lastint_from_price'))
    elif stop_price.endswith('_candle'):
        top_candle_types = {
            '_top_hight_candle': 'hight',
            '_top_low_candle': 'low',
            '_top_open_candle': 'open',
            '_top_close_candle': 'close'
        }

        for candle_type, candle_value in top_candle_types.items():
            if stop_price.endswith(candle_type):
                path = stop_price.split('/')
                if len(path) == 3:
                    path[2] = path[2].strip(candle_type)
                    top_price = await get_top_candle_price(api_key, api_secret, symbol, int(path[2]), candle_value, path[1])
                    stop_price = await get_adjusted_stop_price(api_key, api_secret, price, path[0], top_price, side, symbol)
                break
    return get_adjust_precision_price(symbol, stop_price)
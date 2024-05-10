from funtion.binance.futures.order.other.get_adjust_precision_price import get_adjust_precision_price
from funtion.binance.futures.order.other.get_reduce_lastdecimal import get_reduce_lastdecimal
from funtion.binance.futures.order.other.get_top_candle_price import get_top_candle_price

async def get_adjusted_price(api_key, api_secret, price, latest_price, side, symbol):
    if price.upper() == "NOW" or price is None:
        price = get_reduce_lastdecimal(symbol, latest_price, 1 if side.upper() == 'BUY' else -1)
    elif price.endswith('%'):
        price = latest_price + ((latest_price * float(price.strip('%'))) / 100)
    elif price.endswith('_lastdecimal'):
        price = get_reduce_lastdecimal(symbol, latest_price, price.strip('_lastdecimal'))
    elif price.endswith('_lastint'):
        price = latest_price + float(price.strip('_lastint'))
    elif price.endswith('_candle'):
        top_candle_types = {
            '_top_hight_candle': 'hight',
            '_top_low_candle': 'low',
            '_top_open_candle': 'open',
            '_top_close_candle': 'close'
        }

        for candle_type, candle_value in top_candle_types.items():
            if price.endswith(candle_type):
                path = price.split('/')
                if len(path) == 3:
                    path[2] = path[2].strip(candle_type)
                    top_price = await get_top_candle_price(api_key, api_secret, symbol, int(path[2]), candle_value, path[1])
                    price = await get_adjusted_price(api_key, api_secret, path[0], top_price, side, symbol)
                break
    return get_adjust_precision_price(symbol, price)
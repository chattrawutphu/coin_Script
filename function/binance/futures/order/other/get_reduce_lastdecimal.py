from funtion.binance.futures.order.other.get_adjust_precision_price import get_adjust_precision_price

def get_reduce_lastdecimal(symbol, price, reduce_amount):
    reduce_amount = int(reduce_amount)
    if isinstance(price, int):
        decimal = 1
    else:
        decimal_places = len(str(price).split('.')[1])
        decimal_value = 1 / (10 ** decimal_places)
        decimal = float(decimal_value)
    price = price + (decimal * reduce_amount)
    return get_adjust_precision_price(symbol=symbol, price=price)
     
from binance.client import Client
from config import api_key, api_secret
from function.data.order.get_open_order import get_open_order

client = Client(api_key, api_secret)
def get_stoploss_limit_order(symbol):
    orders = client.futures_get_open_orders(symbol=symbol)

    get_order = get_open_order(symbol)
    if get_order == None:
        return
    side = get_order.get('side')

    if side == None:
        if float(get_order.get('positionAmt')) > 0:
            side = 'BUY'
        else:
            side = 'SELL'
    
    price = None
    if get_order.get('stopPrice') != None:
        price = float(get_order.get('stopPrice'))
    
    if price == None or price == 0:
        if get_order.get('price') != None:
            price = float(get_order.get('price'))

    if price == None or price == 0:
        if get_order.get('entryPrice') != None:
            price = float(get_order.get('entryPrice'))

    for order in orders:
        if order['type'] == Client.ORDER_TYPE_LIMIT and order['reduceOnly']:
            if side == 'BUY':
                if price > float(order['price']):
                    return order
            elif side == 'SELL':
                if price < float(order['price']):
                    return order
    return None
from binance.client import Client
from config import api_key, api_secret
from function.data.order.get_open_order import get_open_order

client = Client(api_key, api_secret)
def get_stoploss_order(symbol):
    orders = client.futures_get_open_orders(symbol=symbol)
    stoploss_orders = []
    
    open_order = get_open_order(symbol)
    if open_order == None:
        return
    
    side = open_order.get('side')
    price = open_order.get('stopPrice')

    if side == None:
        if float(open_order.get('positionAmt')) > 0:
            side = 'BUY'
        else:
            side = 'SELL'
    
    if price == None or price == '0':
        price = open_order.get('price')

    if price == None or price == '0':
        price = open_order.get('entryPrice')
    
    hasTakeprofit = False
    for order in orders:
        if order['reduceOnly']:
            if order['type'] == Client.FUTURE_ORDER_TYPE_TAKE_PROFIT_MARKET or  order['type'] == Client.FUTURE_ORDER_TYPE_TAKE_PROFIT:
                hasTakeprofit == True
                break

    for order in orders:
        if order['reduceOnly']:
            if order['type'] == Client.ORDER_TYPE_LIMIT and hasTakeprofit == True:
                return(order)
            elif order['type'] == Client.FUTURE_ORDER_TYPE_STOP:
                return(order)
            elif order['type'] == Client.FUTURE_ORDER_TYPE_STOP_MARKET:
                return(order)
    return None
from binance.client import Client
from funtion import *
from funtion.binance.futures.order.get_limit_order import get_limit_order
from funtion.binance.futures.order.get_open_position import get_open_position
from funtion.binance.futures.order.get_stop_order import get_stop_order

percent_gap_stop_loss = 0.00001

def create_stop_loss(api_key, api_secret, symbol, stop_price, type, percentage):
    client = Client(api_key, api_secret)
    percentage = float(percentage)
    position = client.futures_position_information(symbol=symbol)
    
    side = None
    
    if len(position) > 0:
        if float(position[0]['positionAmt']) > 0:
            side = 'SELL'
            position_quantity = float(position[0]['positionAmt'])
        elif float(position[0]['positionAmt']) < 0:
            side = 'BUY'
            position_quantity = abs(float(position[0]['positionAmt']))
    if side == None:
        open_orders = client.futures_get_open_orders(symbol=symbol)
        for order in open_orders:
            if order['reduceOnly'] == False:
                side = 'BUY' if order['side'] == 'SELL' else 'SELL'
                position_quantity = float(order['origQty'])
                break
    quantity = position_quantity * (percentage / 100)

    if '%' in stop_price:
        order = get_limit_order(api_key, api_secret, symbol)
        if order == None:
            order = get_stop_order(api_key, api_secret, symbol)
        if order == None:
            order = get_open_position(api_key, api_secret, symbol)
        percentage = float(stop_price.rstrip('%'))
        if side == 'SELL':
            if order.get('price') != None and float(order.get('price')) == 0:
                stop_price = float(order['stopPrice']) - (float(order['stopPrice']) * percentage / 100)
            elif order.get('price') == None:
                stop_price = float(order['entryPrice']) - (float(order['entryPrice']) * percentage / 100)
            else:
                stop_price = float(order['price']) - (float(order['price']) * percentage / 100)
        elif side == 'BUY':
            if order.get('price') != None and float(order.get('price')) == 0:
                stop_price = float(order['stopPrice']) + (float(order['stopPrice']) * percentage / 100)
            elif order.get('price') == None:
                stop_price = float(order['entryPrice']) + (float(order['entryPrice']) * percentage / 100)
            else:
                stop_price = float(order['price']) + (float(order['price']) * percentage / 100)
    else:
        if stop_price.endswith('candle'):
            num_candles = int(stop_price.split('candle')[0])
            candles = client.futures_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_4HOUR, limit=num_candles)
            if side == 'SELL':
                candle_prices = [float(candle[3]) for candle in candles]
                stop_price = min(candle_prices)
            elif side == 'BUY':
                candle_prices = [float(candle[2]) for candle in candles]
                stop_price = max(candle_prices)
        else:
            stop_price = float(stop_price)

    if side == 'SELL': #order จริง = BUY
        stop_price = stop_price * (1 - percent_gap_stop_loss)
    elif side == 'BUY':
        stop_price = stop_price * (1 + percent_gap_stop_loss)

    price_precision = get_decimal_places(get_latest_futures_price(api_key, api_secret, symbol))
    stop_price = round(stop_price, price_precision)
    
    if side == 'SELL':
        price = reduce_decimal(api_key, api_secret, stop_price,1,symbol)
    elif side == 'BUY':
        price = reduce_decimal(api_key, api_secret, stop_price,-1,symbol)

    price = round(price, price_precision)
    
    if type == "stop_limit":
        stop_order = client.futures_create_order(
            symbol=symbol,
            side=side,
            type=Client.FUTURE_ORDER_TYPE_STOP,
            quantity=quantity,
            stopPrice=stop_price,
            price=price,
            reduceOnly=True
        )
    elif type == "stop_market":
        stop_order = client.futures_create_order(
            symbol=symbol,
            side=side,
            type=Client.FUTURE_ORDER_TYPE_STOP_MARKET,
            quantity=quantity,
            stopPrice=stop_price,
            reduceOnly=True
        )
    return stop_order
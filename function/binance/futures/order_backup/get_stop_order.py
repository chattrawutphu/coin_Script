from binance.client import Client


def get_stop_order(api_key, api_secret, symbol):
    client = Client(api_key, api_secret)
    orders = client.futures_get_open_orders(symbol=symbol)

    for order in orders:
        if order['type'] in [Client.FUTURE_ORDER_TYPE_STOP, Client.FUTURE_ORDER_TYPE_STOP_MARKET] and not order['reduceOnly']:
            return order

    return None
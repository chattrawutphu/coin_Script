from binance.client import Client


def get_limit_order(api_key, api_secret, symbol):
    client = Client(api_key, api_secret)
    orders = client.futures_get_open_orders(symbol=symbol)

    for order in orders:
        if order['type'] == Client.ORDER_TYPE_LIMIT and not order['reduceOnly']:
            return order

    return None
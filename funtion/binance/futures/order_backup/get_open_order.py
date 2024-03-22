from binance.client import Client
from get_limit_order import get_limit_order
from get_open_position import get_open_position
from get_stop_order import get_stop_order



def get_open_order(api_key, api_secret, symbol):
    order = get_limit_order(api_key, api_secret, symbol)
    if order == None:
        order = get_stop_order(api_key, api_secret, symbol)
    if order == None:
        order = get_open_position(api_key, api_secret, symbol)
    if order != None:
        return order
    return None
from binance.client import Client
from config import api_key, api_secret

client = Client(api_key, api_secret)
def get_all_order():
    orders = client.futures_get_open_orders()
    return orders
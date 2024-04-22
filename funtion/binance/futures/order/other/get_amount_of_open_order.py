import ccxt.async_support as ccxt
from config import default_testnet as testnet
from funtion.binance.futures.system.create_future_exchange import create_future_exchange

async def get_amount_of_open_order(api_key, api_secret, symbol):

  exchange = await create_future_exchange(api_key, api_secret)

  orders = await exchange.fetch_open_orders(symbol)

  amount = 0
  for order in orders:
    if order['info']['reduce_only'] is False:
      amount += order['amount']

  return amount


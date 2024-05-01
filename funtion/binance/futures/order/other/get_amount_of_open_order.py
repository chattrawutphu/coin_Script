import ccxt.async_support as ccxt
from config import default_testnet as testnet
from funtion.binance.futures.order.other.get_adjust_precision_quantity import get_adjust_precision_quantity
from funtion.binance.futures.system.create_future_exchange import create_future_exchange

async def get_amount_of_open_order(api_key, api_secret, symbol):

  exchange = await create_future_exchange(api_key, api_secret)

  orders = await exchange.fetch_open_orders(symbol)
  await exchange.close()

  amount = 0
  for order in orders:
    if order['info']['positionSide'] == "BOTH":
      if order['info']['reduceOnly'] is False and order['info']['closePosition'] is False:
        amount += float(order['amount'])
    else:
      if order['info']['positionSide'] == "LONG" and order['info']['side'] == "BUY":
        amount += float(order['amount'])
      elif order['info']['positionSide'] == "SHORT" and order['info']['side'] == "SELL":
          amount += float(order['amount'])
     
  get_adjust_precision_quantity(symbol, amount)
  return amount


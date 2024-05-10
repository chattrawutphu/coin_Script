import ccxt.async_support as ccxt
from config import default_testnet as testnet
from funtion.binance.futures.order.other.get_adjust_precision_quantity import get_adjust_precision_quantity
from funtion.binance.futures.system.create_future_exchange import create_future_exchange

async def get_amount_of_position(api_key, api_secret, symbol):

  exchange = await create_future_exchange(api_key, api_secret)

  positions = await exchange.fetch_positions()
  await exchange.close()

  for position in positions:
    if position['symbol'] == symbol:
      print(position)
      amount = await get_adjust_precision_quantity(symbol, float(position['amount']))
      return amount

  return 0


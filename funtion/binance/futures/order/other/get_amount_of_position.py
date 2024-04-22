import ccxt.async_support as ccxt
from config import default_testnet as testnet
from funtion.binance.futures.system.create_future_exchange import create_future_exchange

async def get_amount_of_position(api_key, api_secret, symbol):

  exchange = await create_future_exchange(api_key, api_secret)

  positions = await exchange.fetch_positions()

  for position in positions:
    if position['symbol'] == symbol:
      return position['amount']

  return None


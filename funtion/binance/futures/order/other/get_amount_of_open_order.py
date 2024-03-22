import ccxt.async_support as ccxt
from config import default_testnet as testnet

async def get_amount_of_open_order(api_key, api_secret, symbol):

  exchange = ccxt.binance(config={
    'apiKey': api_key,
    'secret': api_secret,
    'enableRateLimit': True,
    'options': {'defaultType': 'future'},
    })

  exchange.set_sandbox_mode(testnet)

  orders = await exchange.fetch_open_orders(symbol)

  amount = 0
  for order in orders:
    if order['info']['reduce_only'] is False:
      amount += order['amount']

  return amount


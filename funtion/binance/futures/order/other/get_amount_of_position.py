import ccxt.async_support as ccxt
from config import default_testnet as testnet

async def get_amount_of_position(api_key, api_secret, symbol):

  exchange = ccxt.binance(config={
    'apiKey': api_key,
    'secret': api_secret,
    'enableRateLimit': True,
    'options': {'defaultType': 'future'},
    })

  exchange.set_sandbox_mode(testnet)

  positions = await exchange.fetch_positions()

  for position in positions:
    if position['symbol'] == symbol:
      return position['amount']

  return None


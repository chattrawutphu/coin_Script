from function.binance.futures.order.other.get_amount_of_position import get_amount_of_position


async def check_position(api_key, api_secret, symbol):
  if await get_amount_of_position(api_key, api_secret, symbol) != 0:
    return True
  return False

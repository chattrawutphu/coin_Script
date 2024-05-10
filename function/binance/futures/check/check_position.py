import traceback
from function.binance.futures.order.other.get_amount_of_position import get_amount_of_position
from function.message import message


async def check_position(api_key, api_secret, symbol):
  try:
    if await get_amount_of_position(api_key, api_secret, symbol) != 0:
      return True
    return False
  except Exception as e:
    error_traceback = traceback.format_exc()
    message(f"พบข้อผิดพลาด","yellow")
    print(f"Error: {error_traceback}")
    return False

import traceback
from function.binance.futures.order.other.get_amount_of_position import get_amount_of_position
from function.message import message


async def check_position(api_key, api_secret, symbol):
    try:
        amount = await get_amount_of_position(api_key, api_secret, symbol)
        if amount != 0:
            return True
        return False
    except Exception as e:
        error_traceback = traceback.format_exc()
        message("พบข้อผิดพลาด", "yellow")
        message(symbol, f"Error: {error_traceback}", "red")
        return False
from decimal import ROUND_UP, Decimal, ROUND_DOWN, ROUND_HALF_UP
from function.binance.futures.order.other.get_future_market_price import get_future_market_price
from function.binance.futures.system.load_json_data import load_json_data
from function.message import message
from config import api_key, api_secret

async def get_adjust_precision_quantity(symbol, price):
    symbol_data = await load_json_data("json/symbol_precision.json")
    precision = next((item["precision"]["amount"] for item in symbol_data if item["id"] == symbol), 0)
    return float(Decimal(price).quantize(Decimal('1e-{}'.format(precision)), rounding=ROUND_DOWN))
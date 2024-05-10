from decimal import Decimal, ROUND_DOWN
from function.binance.futures.system.load_json_data import load_json_data

async def get_adjust_precision_quantity(symbol, price):
    symbol_data = await load_json_data("json/symbol_precision.json")
    precision = next((item["precision"]["amount"] for item in symbol_data if item["id"] == symbol), 0)
    return float(Decimal(price).quantize(Decimal('1e-{}'.format(precision)), rounding=ROUND_DOWN))
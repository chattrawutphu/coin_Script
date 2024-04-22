import json
from decimal import Decimal, ROUND_DOWN

def load_symbol_data():
    with open('symbol_precision.json', 'r') as file:
        return json.load(file)

def get_adjust_precision_price(symbol, price):
    symbol_data = load_symbol_data()
    precision = next((item["precision"]["amount"] for item in symbol_data if item["id"] == symbol), 0)
    return float(Decimal(price).quantize(Decimal('1e-{}'.format(precision)), rounding=ROUND_DOWN))
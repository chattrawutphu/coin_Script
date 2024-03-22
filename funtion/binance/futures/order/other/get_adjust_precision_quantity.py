from decimal import ROUND_DOWN, Decimal
import config

def get_adjust_precision_quantity(symbol, quantity):
    precision = next((item["precision"]["amount"] for item in config.symbol_data if item["id"] == symbol), 0)
    return float(Decimal(quantity).quantize(Decimal('1e-{}'.format(precision)), rounding=ROUND_DOWN))
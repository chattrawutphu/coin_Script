from decimal import ROUND_DOWN, Decimal
import config

def get_adjust_precision_price(symbol, price):
    precision =  next((item["precision"]["price"] for item in config.symbol_data if item["id"] == symbol), 0)
    return float(Decimal(price).quantize(Decimal('1e-{}'.format(precision)), rounding=ROUND_DOWN))
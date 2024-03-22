from binance.client import Client


def get_latest_futures_price(api_key, api_secret, symbol):
    client = Client(api_key, api_secret)
    ticker = client.futures_symbol_ticker(symbol=symbol)
    market_price = float(ticker['price'])
    return market_price

# def get_decimal_places(number):
#     str_number = str(number)
#     if "." in str_number:
#         decimal_places = len(str_number) - str_number.index(".") - 1
#         return decimal_places
#     else:
#         return 0

# def check_decimal_places(number):
#     if isinstance(number, int):
#         return 1
#     else:
#         decimal_places = len(str(number).split('.')[1])
#         decimal_value = 1 / (10 ** decimal_places)
#         return float(decimal_value)

# def reduce_decimal(api_key, api_secret, number, amount, symbol):
#     decimal = check_decimal_places(get_latest_futures_price(api_key, api_secret, symbol))
#     number2 = number + (decimal * amount)
#     return number2

# def get_futures_account_info(api_key, api_secret):
#     client = Client(api_key, api_secret)
#     account_info = client.futures_account()
#     return account_info

# ----get_future_available_balance----

# def get_futures_balance(api_key, api_secret, symbol):
#     account_info = get_futures_account_info(api_key, api_secret)
#     balance = 0.0
#     for asset in account_info['assets']:
#         if asset['asset'] == symbol:
#             balance = float(asset['availableBalance'])
#             break
#     return balance

# def get_asset_precision(api_key, api_secret, symbol):
#     client = Client(api_key, api_secret)
#     symbol_info = client.futures_exchange_info()
#     symbol_data = next((item for item in symbol_info['symbols'] if item['symbol'] == symbol), None)

#     if symbol_data:
#         quantity_precision = symbol_data['quantityPrecision']
#         return quantity_precision

#     raise Exception(f"Symbol '{symbol}' not found in exchange info.")

# def adjust_quantity(api_key, api_secret, symbol, quantity):
#     precision = get_asset_precision(api_key, api_secret, symbol)

#     usdt_balance = get_futures_balance(api_key, api_secret, 'USDT')
#     adjusted_quantity = min(quantity, usdt_balance)
#     adjusted_quantity = round(adjusted_quantity, precision)

#     return adjusted_quantity

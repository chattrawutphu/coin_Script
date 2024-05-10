from binance.client import Client
from function.binance.futures.order.funtion import adjust_quantity, get_decimal_places, get_futures_balance

def calculate_amount(api_key, api_secret, amount):
    usdt_balance = get_futures_balance(api_key, api_secret, 'USDT')
    
    if isinstance(amount, str) and amount.endswith('%'):
        if amount.lower() == 'max':
            amount = usdt_balance
        else:
            percentage = float(amount[:-1]) / 100.0
            amount = usdt_balance * percentage
    else:
        amount = float(amount)

    return min(amount, usdt_balance)

def calculate_quantity(api_key, api_secret, symbol, amount):
    price = float(Client(api_key, api_secret).get_symbol_ticker(symbol=symbol)["price"])
    quantity = amount / price
    return adjust_quantity(api_key, api_secret, symbol, quantity)

def create_order(api_key, api_secret, symbol, amount, side, order_type, price=None):
    client = Client(api_key, api_secret)
    
    amount = calculate_amount(api_key, api_secret, amount)
    quantity = calculate_quantity(api_key, api_secret, symbol, amount)

    if order_type == 'limit':
        current_price = float(client.get_symbol_ticker(symbol=symbol)["price"])
        if isinstance(price, str) and price.endswith('%'):
            percentage_change = float(price[:-1]) / 100.0
            if side.lower() == 'buy':
                price = current_price * (1 - percentage_change)
            elif side.lower() == 'sell':
                price = current_price * (1 + percentage_change)
        else:
            price = float(price)
        
        price_precision = get_decimal_places(price)
        price = round(price, price_precision)

        order = client.create_order(
            symbol=symbol,
            side=side,
            type=Client.ORDER_TYPE_LIMIT,
            timeInForce=Client.TIME_IN_FORCE_GTC,
            price=price,
            quantity=quantity
        )
    elif order_type == 'market':
        order = client.create_order(
            symbol=symbol,
            side=side,
            type=Client.ORDER_TYPE_MARKET,
            quoteOrderQty=quantity
        )
    elif order_type == 'stop_market':
        current_price = float(client.get_symbol_ticker(symbol=symbol)["price"])
        if isinstance(price, str) and price.endswith('%'):
            percentage_change = float(price[:-1]) / 100.0
            if side.lower() == 'buy':
                price = current_price * (1 + percentage_change)
            elif side.lower() == 'sell':
                price = current_price * (1 - percentage_change)
        else:
            price = float(price)
        
        price_precision = get_decimal_places(price)
        price = round(price, price_precision)

        order = client.create_order(
            symbol=symbol,
            side=side,
            type=Client.FUTURE_ORDER_TYPE_STOP_MARKET,
            stopPrice=price,
            quantity=quantity
        )

    return order

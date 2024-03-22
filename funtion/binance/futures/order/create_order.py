import traceback
import ccxt.async_support as ccxt
from config import default_testnet as testnet

from funtion.message import message
from funtion.binance.futures.order.other.get_future_available_balance import get_future_available_balance
from funtion.binance.futures.order.other.get_adjust_precision_quantity import get_adjust_precision_quantity
from funtion.binance.futures.order.other.get_future_market_price import get_future_market_price
from funtion.binance.futures.order.other.get_position_mode import get_position_mode
from funtion.binance.futures.order.other.get_create_order_adjusted_price import get_adjusted_price
from funtion.binance.futures.order.other.get_create_order_adjusted_stop_price import get_adjusted_stop_price

async def create_order(api_key, api_secret, symbol, side, price=0, quantity=0, order_type="MARKET", stop_price=None):
    try:
        exchange = ccxt.binance({
            'apiKey': api_key,
            'secret': api_secret,
            'enableRateLimit': True,
            'options': {'defaultType': 'future'},
        })
        exchange.set_sandbox_mode(testnet)

        latest_price = await get_future_market_price(api_key, api_secret, symbol)
        price = await get_adjusted_price(api_key, api_secret, price, latest_price, side, symbol)
        quantity = await get_adjusted_quantity(api_key, api_secret, quantity, price, symbol)
        mode = await get_position_mode(api_key, api_secret, symbol)

        if mode == 'hedge':
            await clear_order_and_position(api_key, api_secret)
            await exchange.set_position_mode(hedged=False)

        params = {}

        if order_type.upper() == "MARKET":
            params.update({'type': 'market'})
        elif order_type.upper() == "STOP_MARKET":
            params.update({'type': 'stop_market', 'stopPrice': price})
        elif order_type.upper() == "STOP_LIMIT":
            stop_price = await get_adjusted_stop_price(api_key, api_secret, price, stop_price, latest_price, side, symbol)
            params.update({'type': 'stop', 'price': stop_price, 'stopPrice': price})
        else:
            params.update({'type': 'limit', 'price': price})

        order_params = {
            'symbol': symbol,
            'side': side,
            'type': params['type'],
            'amount': quantity,
            'params': params
        }

        message(symbol, f"{order_params}","yellow")

        if params['type'] != 'market' and params['type'] != 'stop_market':
            order_params['price'] = params['price']
        
        order = await exchange.create_order(**order_params)

        await exchange.close()
        return order

    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"พบข้อผิดพลาด","yellow")
        print(f"Error: {error_traceback}")
        await exchange.close()
    return None

async def get_adjusted_quantity(api_key, api_secret, quantity, price, symbol):
    available_balance = await get_future_available_balance(api_key, api_secret)

    if quantity.upper() == "MAX":
        btc_quantity = available_balance / price
    elif quantity.endswith('%'):
        btc_quantity = (float(quantity.strip('%')) / 100) * available_balance / price
    elif quantity.endswith('$'):
        btc_quantity = float(quantity.strip('$')) / price
    else:
        btc_quantity = float(quantity)
    return get_adjust_precision_quantity(symbol, btc_quantity)
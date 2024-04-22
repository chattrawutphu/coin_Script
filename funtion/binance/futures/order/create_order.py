import traceback
import ccxt.async_support as ccxt
from config import default_testnet as testnet

from funtion.binance.futures.order.other.cache.get_cache_position_mode import get_cache_position_mode
from funtion.binance.futures.order.other.cache.change_cache_position_mode import change_cache_position_mode
from funtion.binance.futures.system.create_future_exchange import create_future_exchange
from funtion.message import message
from funtion.binance.futures.order.other.get_future_available_balance import get_future_available_balance
from funtion.binance.futures.order.other.get_adjust_precision_quantity import get_adjust_precision_quantity
from funtion.binance.futures.order.other.get_future_market_price import get_future_market_price
from funtion.binance.futures.order.other.get_position_mode import get_position_mode
from funtion.binance.futures.order.other.get_create_order_adjusted_price import get_adjusted_price
from funtion.binance.futures.order.other.get_create_order_adjusted_stop_price import get_adjusted_stop_price

async def create_order(api_key, api_secret, symbol, side, price="now", quantity="30$", order_type="MARKET", stop_price=None):
    try:
        exchange = await create_future_exchange(api_key, api_secret)

        latest_price = await get_future_market_price(api_key, api_secret, symbol)
        price = await get_adjusted_price(api_key, api_secret, price, latest_price, side, symbol)
        temp_quantity = quantity
        quantity = await get_adjusted_quantity(api_key, api_secret, quantity, price, symbol)

        params = {}

        #mode = await get_position_mode(api_key, api_secret, symbol)
        mode = await get_cache_position_mode(api_key, api_secret)

        if mode == 'hedge':
6
                if side == "buy": params.update({'positionSide': 'short'})
                else: params.update({'positionSide': 'long'})

            if order_type.upper() == "TAKE_PROFIT_MARKET" or order_type.upper() == "STOPLOSS_MARKET":
                if temp_quantity.upper() == "MAX" or temp_quantity.endswith('100%'):
                    params.update({'closePosition': True})
        else:
            if order_type.upper() == "TAKE_PROFIT_MARKET" or order_type.upper() == "STOPLOSS_MARKET":
                if temp_quantity.upper() == "MAX" or temp_quantity.endswith('100%'):
                    params.update({'closePosition': True})
                else:
                    params.update({'reduceOnly': True})
        #     await clear_order_and_position(api_key, api_secret)
        #     await exchange.set_position_mode(hedged=False)

        if order_type.upper() == "MARKET":
            params.update({'type': 'market'})
        elif order_type.upper() == "STOP_MARKET" or order_type.upper() == "STOPLOSS_MARKET":
            params.update({'type': 'stop_market', 'stopPrice': price})
        elif order_type.upper() == "STOP_LIMIT":
            stop_price = await get_adjusted_stop_price(api_key, api_secret, price, stop_price, latest_price, side, symbol)
            params.update({'type': 'stop', 'price': stop_price, 'stopPrice': price})

        elif order_type.upper() == "TAKE_PROFIT_MARKET":
            params.update({'type': 'take_profit_market', 'stopPrice': price})

        else:
            params.update({'type': 'limit', 'price': price})

        order_params = {
            'symbol': symbol,
            'side': side,
            'type': params['type'],
            'amount': quantity,
            'params': params
        }

        # if 'closePosition' in params:
        #    del order_params['amount']

        message(symbol, f"{order_params}","yellow")

        if params['type'] != 'market' and params['type'] != 'stop_market' and params['type'] != 'take_profit_market':
            order_params['price'] = params['price']
        
        order = await exchange.create_order(**order_params)

        await exchange.close()
        return order
    except Exception as e:
        error_traceback = traceback.format_exc()
        if "Order's position side does not match user's setting" in str(error_traceback):
            if order_type.upper() == "TAKE_PROFIT_MARKET" or order_type.upper() == "STOPLOSS_MARKET":
                if 'reduceOnly' in params:
                    del params['reduceOnly']
            else:
                if 'positionSide' in params:
                    del params['positionSide']
                else:
                    if side == "buy": params.update({'positionSide': 'long'})
                    else: params.update({'positionSide': 'short'})
            try:
                message(symbol, f"Position Mode ไม่ถูกต้อง ลองเปลี่ยนอีกครั้ง และเก็บข้อมูลไว้","yellow")
                await change_cache_position_mode(api_key, api_secret)
                order = await exchange.create_order(**order_params)
                await exchange.close()
                return order
            except Exception as e:
                message(symbol, f"พบข้อผิดพลาด","yellow")
                print(f"Error: {error_traceback}")
                await exchange.close()
            
        else:
            message(symbol, f"พบข้อผิดพลาด","yellow")
            print(f"Error: {error_traceback}")
            await exchange.close()
    return None

async def get_adjusted_quantity(api_key, api_secret, quantity, price, symbol):
    available_balance = await get_future_available_balance(api_key, api_secret)

    if quantity.upper() == "MAX" or quantity.endswith('100%'):
        btc_quantity = available_balance / price
    elif quantity.endswith('%'):
        btc_quantity = (float(quantity.strip('%')) / 100) * available_balance / price
    elif quantity.endswith('$'):
        btc_quantity = float(quantity.strip('$')) / price
    else:
        btc_quantity = float(quantity)
    return get_adjust_precision_quantity(symbol, btc_quantity)
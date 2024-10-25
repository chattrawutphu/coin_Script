import traceback
import ccxt.async_support as ccxt
from config import default_testnet as testnet

from function.binance.futures.order.other.get_position_mode import get_position_mode, change_position_mode
from function.binance.futures.order.other.get_amount_of_open_order import get_amount_of_open_order
from function.binance.futures.order.other.get_amount_of_position import get_amount_of_position
from function.binance.futures.system.create_future_exchange import create_future_exchange
from function.message import message
from function.binance.futures.order.other.get_future_available_balance import get_future_available_balance
from function.binance.futures.order.other.get_adjust_precision_quantity import get_adjust_precision_quantity
from function.binance.futures.order.other.get_future_market_price import get_future_market_price
from function.binance.futures.order.other.get_create_order_adjusted_price import get_adjusted_price
from function.binance.futures.order.other.get_create_order_adjusted_stop_price import get_adjusted_stop_price

async def create_order(api_key, api_secret, symbol, side, price="now", quantity="30$", order_type="MARKET", stop_price=None):
    exchange = None
    try:
        exchange = await create_future_exchange(api_key, api_secret)

        latest_price = await get_future_market_price(api_key, api_secret, symbol)
        price = await get_adjusted_price(api_key, api_secret, price, latest_price, side, symbol)
        temp_quantity = quantity
        quantity = await get_adjusted_quantity(api_key, api_secret, quantity, price, symbol, order_type)

        params = {}

        mode = await get_position_mode(api_key, api_secret)

        if mode == 'hedge':
            if order_type.upper() == "TAKE_PROFIT_MARKET" or order_type.upper() == "STOPLOSS_MARKET":
                if side == "buy": params.update({'positionSide': 'short'})
                else: params.update({'positionSide': 'long'})
            else:
                if side == "buy": params.update({'positionSide': 'long'})
                else: params.update({'positionSide': 'short'})

            if order_type.upper() == "TAKE_PROFIT_MARKET" or order_type.upper() == "STOPLOSS_MARKET":
                if temp_quantity.upper() == "MAX" or temp_quantity.endswith('100%'):
                    params.update({'closePosition': True})
        else:
            if order_type.upper() == "TAKE_PROFIT_MARKET" or order_type.upper() == "STOPLOSS_MARKET":
                if temp_quantity.upper() == "MAX" or temp_quantity.endswith('100%'):
                    params.update({'closePosition': True})
                else:
                    params.update({'reduceOnly': True})

        if order_type.upper() == "MARKET":
            params.update({'type': 'market'})
        elif order_type.upper() == "STOP_MARKET" or order_type.upper() == "STOPLOSS_MARKET":
            params.update({'type': 'stop_market', 'stopPrice': price})
            if quantity == 0:
                quantity == await get_adjust_precision_quantity(symbol, (latest_price/100))
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

        if params['type'] != 'market' and params['type'] != 'stop_market' and params['type'] != 'take_profit_market':
            order_params['price'] = params['price']
        
        try:
            order = await exchange.create_order(**order_params)
            await exchange.close()
            return order
        except ccxt.OrderImmediatelyFillable:
            # ถ้าเกิด error "Order would immediately trigger" ให้เปลี่ยนเป็น market order
            message(symbol, "คำสั่งจะทำงานทันที เปลี่ยนเป็น Market Order", "yellow")
            
            # เปลี่ยนเป็น market order
            market_params = {
                'symbol': symbol,
                'side': side,
                'type': 'market',
                'amount': quantity,
                'params': {'type': 'market'}
            }
            
            if mode == 'hedge':
                if side == "buy":
                    market_params['params'].update({'positionSide': 'long'})
                else:
                    market_params['params'].update({'positionSide': 'short'})
            
            order = await exchange.create_order(**market_params)
            message(symbol, f"เข้า {side.upper()} ด้วย Market Order สำเร็จที่ราคา {float(order['average']):.2f}", "green")
            await exchange.close()
            return order

    except Exception as e:
        error_traceback = traceback.format_exc()
        if "Order's position side does not match user's setting" in str(error_traceback):
            if order_type.upper() == "TAKE_PROFIT_MARKET" or order_type.upper() == "STOPLOSS_MARKET":
                if 'reduceOnly' in params:
                    del params['reduceOnly']
                else:
                    params.update({'reduceOnly': True})
                if 'positionSide' in params:
                    del params['positionSide']
                else:
                    if side == "buy": params.update({'positionSide': 'short'})
                    else: params.update({'positionSide': 'long'})
                if 'closePosition' in params:
                    del params['reduceOnly']
            else:
                if 'positionSide' in params:
                    del params['positionSide']
                else:
                    if side == "buy": params.update({'positionSide': 'long'})
                    else: params.update({'positionSide': 'short'})
            try:
                message(symbol, f"Position Mode ไม่ถูกต้อง ลองเปลี่ยนอีกครั้ง และเก็บข้อมูลไว้","yellow")
                await change_position_mode(api_key, api_secret)
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
    finally:
        if exchange:
            try:
                await exchange.close()
            except Exception as e:
                message(symbol, f"เกิดข้อผิดพลาดในการปิด exchange: {str(e)}", "red")
    return None

async def get_adjusted_quantity(api_key, api_secret, quantity, price, symbol, order_type=None):
    try:
        # Ensure quantity is a string before performing string operations
        price = float(price)
        quantity_str = str(quantity)

        if order_type and order_type.upper() in ["TAKE_PROFIT_MARKET", "STOPLOSS_MARKET"]:
            if quantity_str.upper() == "MAX" or quantity_str.endswith('100%'):
                position_amount = float(await get_amount_of_position(api_key, api_secret, symbol))
                open_order_amount = float(await get_amount_of_open_order(api_key, api_secret, symbol))
                btc_quantity = position_amount + open_order_amount
            elif quantity_str.endswith('%'):
                position_amount = float(await get_amount_of_position(api_key, api_secret, symbol))
                open_order_amount = float(await get_amount_of_open_order(api_key, api_secret, symbol))
                percentage = float(quantity_str.strip('%')) / 100
                btc_quantity = (position_amount + open_order_amount) * percentage
            elif quantity_str.endswith('$'):
                if price <= 0:
                    raise ValueError(f"Invalid price for {symbol}: {price}")
                btc_quantity = float(quantity_str.strip('$')) / price
            else:
                btc_quantity = float(quantity)
        else:
            available_balance = await get_future_available_balance(api_key, api_secret)
            if available_balance is None:
                raise ValueError(f"Could not get available balance for {symbol}")
            available_balance = float(available_balance)

            if quantity_str.upper() == "MAX" or quantity_str.endswith('100%'):
                if price <= 0:
                    raise ValueError(f"Invalid price for {symbol}: {price}")
                btc_quantity = available_balance / price
            elif quantity_str.endswith('%'):
                if price <= 0:
                    raise ValueError(f"Invalid price for {symbol}: {price}")
                percentage = float(quantity_str.strip('%')) / 100
                btc_quantity = (percentage * available_balance) / price
            elif quantity_str.endswith('$'):
                if price <= 0:
                    raise ValueError(f"Invalid price for {symbol}: {price}")
                btc_quantity = float(quantity_str.strip('$')) / price
            else:
                btc_quantity = float(quantity)

        adjusted_quantity = await get_adjust_precision_quantity(symbol, btc_quantity)
        if adjusted_quantity <= 0:
            raise ValueError(f"Invalid adjusted quantity for {symbol}: {adjusted_quantity} | quantity_str: {quantity_str} | price: {price}")
            
        return adjusted_quantity
        
    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"เกิดข้อผิดพลาดในการคำนวณปริมาณ: {str(e)}", "red")
        message(symbol, f"Error: {error_traceback}", "red")
        return None  # เปลี่ยนจาก raise เป็น return None เพื่อให้ฟังก์ชั่นที่เรียกใช้จัดการต่อได้
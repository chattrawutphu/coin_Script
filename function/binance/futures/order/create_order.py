import traceback
import ccxt.async_support as ccxt
from config import default_testnet as testnet
import locale
from decimal import Decimal, InvalidOperation, ROUND_DOWN
import re

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

        # ตรวจสอบและแปลงค่าราคาให้ถูกต้อง
        latest_price = await get_future_market_price(api_key, api_secret, symbol)
        if latest_price is None:
            message(symbol, "ไม่สามารถดึงราคาตลาดได้", "red")
            return None
            
        # แปลงราคาและปริมาณให้เป็นตัวเลขที่ถูกต้อง
        try:
            price = await get_adjusted_price(api_key, api_secret, price, latest_price, side, symbol)
            if price is None:
                message(symbol, "ไม่สามารถปรับราคาได้", "red")
                return None
            
            temp_quantity = quantity
            quantity = await get_adjusted_quantity(api_key, api_secret, quantity, price, symbol, order_type)
            if quantity is None or quantity <= 0:
                message(symbol, f"ปริมาณที่ปรับแล้วไม่ถูกต้อง: {quantity}", "red")
                return None
                
            # แปลงให้เป็น float ที่มีความแม่นยำ
            price = float('{:.8f}'.format(float(price)))
            quantity = float('{:.8f}'.format(float(quantity)))
        except Exception as e:
            message(symbol, f"เกิดข้อผิดพลาดในการแปลงค่าราคาหรือปริมาณ: {str(e)}", "red")
            return None

        params = {}
        
        # ดึง position mode
        mode = await get_position_mode(api_key, api_secret)

        # จัดการตามประเภทคำสั่ง
        if order_type.upper() == "EXIT_MARKET":
            # กรณี EXIT_MARKET (ปิด position)
            params.update({
                'type': 'market'
            })

            if temp_quantity.upper() == "MAX" or temp_quantity.endswith('100%'):
                params.update({'closePosition': True})
            else:
                params.update({'reduceOnly': True})
                
            message(symbol, f"สร้างคำสั่ง EXIT_MARKET {temp_quantity}", "blue")
            
            if mode == 'hedge':
                if side == "buy":
                    params.update({'positionSide': 'short'})
                else:
                    params.update({'positionSide': 'long'})

        else:
            # ตั้งค่า position mode
            if mode == 'hedge':
                if order_type.upper() in ["TAKE_PROFIT_MARKET", "STOPLOSS_MARKET"]:
                    if side == "buy":
                        params.update({'positionSide': 'short'})
                    else:
                        params.update({'positionSide': 'long'})
                else:
                    if side == "buy":
                        params.update({'positionSide': 'long'})
                    else:
                        params.update({'positionSide': 'short'})

                if order_type.upper() in ["TAKE_PROFIT_MARKET", "STOPLOSS_MARKET"]:
                    if temp_quantity.upper() == "MAX" or temp_quantity.endswith('100%'):
                        params.update({'closePosition': True})
            else:
                if order_type.upper() in ["TAKE_PROFIT_MARKET", "STOPLOSS_MARKET"]:
                    if temp_quantity.upper() == "MAX" or temp_quantity.endswith('100%'):
                        params.update({'closePosition': True})
                    else:
                        params.update({'reduceOnly': True})

            # ตั้งค่าประเภทคำสั่ง
            if order_type.upper() == "MARKET":
                params.update({'type': 'market'})
            elif order_type.upper() in ["STOP_MARKET", "STOPLOSS_MARKET"]:
                params.update({
                    'type': 'stop_market',
                    'stopPrice': price
                })
                if quantity == 0:
                    quantity = await get_adjust_precision_quantity(symbol, (latest_price/100))
            elif order_type.upper() == "STOP_LIMIT":
                stop_price = await get_adjusted_stop_price(api_key, api_secret, price, stop_price, latest_price, side, symbol)
                if stop_price is None:
                    message(symbol, "ไม่สามารถปรับราคา stop ได้", "red")
                    return None
                params.update({
                    'type': 'stop',
                    'price': float('{:.8f}'.format(float(stop_price))),
                    'stopPrice': price
                })
            elif order_type.upper() == "TAKE_PROFIT_MARKET":
                params.update({
                    'type': 'take_profit_market',
                    'stopPrice': price
                })
            else:  # LIMIT
                params.update({
                    'type': 'limit',
                    'price': price
                })

        # สร้าง parameters สำหรับคำสั่ง
        order_params = {
            'symbol': symbol,
            'side': side,
            'type': params['type'],
            'amount': quantity,
            'params': params
        }

        if params['type'] not in ['market', 'stop_market', 'take_profit_market']:
            order_params['price'] = params.get('price', price)

        # แสดงรายละเอียดคำสั่งก่อนส่ง
        message(symbol, f"กำลังส่งคำสั่ง: Symbol: {symbol}, Side: {side}, Type: {params['type']}, Amount: {quantity}, Parameters: {params}", "blue")

        try:
            order = await exchange.create_order(**order_params)
            
            # แสดงผลตามประเภทคำสั่ง
            if order_type.upper() == "EXIT_MARKET":
                message(symbol, f"ส่งคำสั่งปิด position {temp_quantity} สำเร็จที่ราคา {float(order['average']):.2f}", "green")
            elif params['type'] == 'market':
                message(symbol, f"ส่งคำสั่ง Market Order สำเร็จที่ราคา {float(order['average']):.2f}", "green")
            else:
                message(symbol, f"ส่งคำสั่ง {order_type} สำเร็จ", "green")
            
            return order

        except ccxt.OrderImmediatelyFillable:
            message(symbol, "คำสั่งจะทำงานทันที", "yellow")
            
            if order_type.upper() != "EXIT_MARKET":
                # เปลี่ยนเป็น market order ยกเว้น EXIT_MARKET
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
                
                message(symbol, f"เปลี่ยนเป็นคำสั่ง Market:", "yellow")
                message(symbol, f"Parameters: {market_params}", "yellow")
                order = await exchange.create_order(**market_params)
            else:
                # สำหรับ EXIT_MARKET ใช้ parameters เดิม
                order = await exchange.create_order(**order_params)
            
            if order_type.upper() == "EXIT_MARKET":
                message(symbol, f"ส่งคำสั่งปิด position {temp_quantity} สำเร็จที่ราคา {float(order['average']):.2f}", "green")
            else:
                message(symbol, f"ส่งคำสั่ง Market Order สำเร็จที่ราคา {float(order['average']):.2f}", "green")
            
            return order

    except Exception as e:
        error_traceback = traceback.format_exc()
        if "Order's position side does not match user's setting" in str(error_traceback):
            if order_type.upper() in ["TAKE_PROFIT_MARKET", "STOPLOSS_MARKET"]:
                if 'reduceOnly' in params:
                    del params['reduceOnly']
                else:
                    params.update({'reduceOnly': True})
                if 'positionSide' in params:
                    del params['positionSide']
                else:
                    if side == "buy":
                        params.update({'positionSide': 'short'})
                    else:
                        params.update({'positionSide': 'long'})
                if 'closePosition' in params:
                    del params['reduceOnly']
            else:
                if 'positionSide' in params:
                    del params['positionSide']
                else:
                    if side == "buy":
                        params.update({'positionSide': 'long'})
                    else:
                        params.update({'positionSide': 'short'})
            try:
                message(symbol, f"Position Mode ไม่ถูกต้อง ลองเปลี่ยนอีกครั้ง และเก็บข้อมูลไว้", "yellow")
                await change_position_mode(api_key, api_secret)
                order = await exchange.create_order(**order_params)
                return order
            except Exception as e:
                message(symbol, f"พบข้อผิดพลาด", "red")
                message(symbol, f"Error: {error_traceback}", "red")
        else:
            message(symbol, f"พบข้อผิดพลาด", "red")
            message(symbol, f"Error: {error_traceback}", "red")
    finally:
        if exchange:
            try:
                await exchange.close()
            except Exception as e:
                message(symbol, f"เกิดข้อผิดพลาดในการปิด exchange: {str(e)}", "red")
    return None

def sanitize_number_string(value):
    """แปลงค่าตัวเลขให้เป็นรูปแบบมาตรฐาน ไม่ขึ้นกับ locale"""
    if isinstance(value, (int, float)):
        return str(value)
    if not isinstance(value, str):
        return str(value)
    # ลบ thousand separator และแปลง decimal separator เป็นจุด
    clean = str(value).replace(',', '').replace(' ', '')
    # แปลงเครื่องหมายทศนิยมอื่นๆ เป็นจุด
    clean = clean.replace('٫', '.').replace('․', '.').replace('·', '.')
    return clean

async def get_adjusted_quantity(api_key, api_secret, quantity, price, symbol, order_type=None):
    """ปรับปริมาณการเทรดตามรูปแบบที่กำหนด"""
    try:
        # เพิ่ม logging สำหรับ debug
        message(symbol, f"Input - quantity: {quantity}, price: {price}, order_type: {order_type}", "debug")

        # ตรวจสอบค่า price
        if price == 'now' or price is None:
            price = await get_future_market_price(api_key, api_secret, symbol)
            if price is None:
                message(symbol, "ไม่สามารถดึงราคาตลาดได้", "red")
                return None

        # ทำความสะอาดและแปลงค่า price
        try:
            price = Decimal(sanitize_number_string(price))
            if price <= Decimal('0'):
                message(symbol, f"ราคาไม่ถูกต้อง: {price}", "red")
                return None
        except (InvalidOperation, ValueError, TypeError) as e:
            message(symbol, f"รูปแบบราคาไม่ถูกต้อง: {price}, error: {str(e)}", "red")
            return None

        # แปลง quantity เป็น string และทำความสะอาด
        quantity_str = str(quantity).strip()

        # คำนวณปริมาณตามรูปแบบคำสั่ง
        try:
            if order_type and order_type.upper() in ["TAKE_PROFIT_MARKET", "STOPLOSS_MARKET", "EXIT_MARKET"]:
                if quantity_str.upper() == "MAX" or quantity_str.endswith('100%'):
                    position_amount = Decimal(sanitize_number_string(
                        await get_amount_of_position(api_key, api_secret, symbol)))
                    open_order_amount = Decimal(sanitize_number_string(
                        await get_amount_of_open_order(api_key, api_secret, symbol)))
                    
                    if position_amount == Decimal('0') and open_order_amount == Decimal('0'):
                        message(symbol, "ไม่มี position และ open orders", "yellow")
                        return None
                    btc_quantity = position_amount + open_order_amount
                    
                elif quantity_str.endswith('%'):
                    position_amount = Decimal(sanitize_number_string(
                        await get_amount_of_position(api_key, api_secret, symbol)))
                    open_order_amount = Decimal(sanitize_number_string(
                        await get_amount_of_open_order(api_key, api_secret, symbol)))
                    
                    if position_amount == Decimal('0') and open_order_amount == Decimal('0'):
                        message(symbol, "ไม่มี position และ open orders สำหรับคำนวณเปอร์เซ็นต์", "yellow")
                        return None
                        
                    clean_quantity = re.sub(r'[^0-9.]', '', quantity_str.rstrip('%'))
                    percentage = Decimal(clean_quantity) / Decimal('100')
                    btc_quantity = (position_amount + open_order_amount) * percentage
                    
                elif quantity_str.endswith('$'):
                    clean_quantity = re.sub(r'[^0-9.]', '', quantity_str.rstrip('$'))
                    btc_quantity = Decimal(clean_quantity) / price
                else:
                    btc_quantity = Decimal(sanitize_number_string(quantity))

            else:  # Normal order
                available_balance = await get_future_available_balance(api_key, api_secret)
                if available_balance is None:
                    message(symbol, "ไม่สามารถดึงข้อมูล available balance", "red")
                    return None
                
                available_balance = Decimal(sanitize_number_string(available_balance))
                if available_balance <= Decimal('0'):
                    message(symbol, "Available balance เป็น 0", "red")
                    return None

                if quantity_str.upper() == "MAX" or quantity_str.endswith('100%'):
                    btc_quantity = available_balance / price
                elif quantity_str.endswith('%'):
                    clean_quantity = re.sub(r'[^0-9.]', '', quantity_str.rstrip('%'))
                    percentage = Decimal(clean_quantity) / Decimal('100')
                    btc_quantity = (percentage * available_balance) / price
                elif quantity_str.endswith('$'):
                    clean_quantity = re.sub(r'[^0-9.]', '', quantity_str.rstrip('$'))
                    btc_quantity = Decimal(clean_quantity) / price
                else:
                    btc_quantity = Decimal(sanitize_number_string(quantity))

            # Log สำหรับ debug
            message(symbol, f"Calculated quantity before precision adjustment: {btc_quantity}", "debug")

            # ปรับความละเอียดของปริมาณ
            adjusted_quantity = await get_adjust_precision_quantity(symbol, float(str(btc_quantity)))
            if adjusted_quantity is None or adjusted_quantity <= 0:
                message(symbol, f"ปริมาณที่ปรับแล้วไม่ถูกต้อง: {adjusted_quantity}", "red")
                return None

            message(symbol, f"Final adjusted quantity: {adjusted_quantity}", "debug")
            return adjusted_quantity

        except (InvalidOperation, ValueError, TypeError) as e:
            message(symbol, f"เกิดข้อผิดพลาดในการคำนวณปริมาณ: {str(e)}", "red")
            return None

    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"เกิดข้อผิดพลาดในการคำนวณปริมาณ: {str(e)}", "red")
        message(symbol, f"Error Traceback: {error_traceback}", "red")
        return None
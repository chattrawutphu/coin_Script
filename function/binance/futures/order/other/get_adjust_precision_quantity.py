from decimal import ROUND_UP, Decimal, ROUND_DOWN, ROUND_HALF_UP
from function.binance.futures.order.other.get_future_market_price import get_future_market_price
from function.binance.futures.system.load_json_data import load_json_data
from function.message import message
from config import api_key, api_secret

async def get_adjust_precision_quantity(symbol, quantity, current_price=None):
    try:
        symbol_data = await load_json_data("json/symbol_precision.json")
        symbol_info = next((item for item in symbol_data if item["id"] == symbol), None)
        
        if not symbol_info:
            message(symbol, f"ไม่พบข้อมูล {symbol} ใน symbol_precision.json", "red")
            return None

        precision = symbol_info["precision"]["amount"]
        min_quantity = symbol_info["limits"]["amount"]["min"]
        min_notional = 100  # กำหนดเป็น 100 USDT ตาม error message
        
        # ถ้าไม่มี current_price ให้ดึงมา
        if not current_price:
            current_price = await get_future_market_price(api_key, api_secret, symbol)
            if not current_price:
                message(symbol, "ไม่สามารถดึงราคาตลาดได้", "red")
                return None

        edt_quantity = float(Decimal(quantity).quantize(Decimal('1e-{}'.format(precision)), rounding=ROUND_DOWN))
        
        if edt_quantity < 0:
            edt_quantity = abs(edt_quantity)

        # คำนวณมูลค่า order
        notional_value = edt_quantity * current_price

        # ถ้ามูลค่าต่ำกว่า minNotional ให้ปรับ quantity
        if notional_value < min_notional:
            min_qty_for_notional = min_notional / current_price
            # ปรับให้เป็นจำนวนที่มากกว่าทั้ง min_quantity และ min_qty_for_notional
            edt_quantity = max(min_quantity, min_qty_for_notional)
            # ปรับให้ตรงกับ precision
            edt_quantity = float(Decimal(str(edt_quantity)).quantize(Decimal('1e-{}'.format(precision)), rounding=ROUND_UP))
            
            # เช็คว่าหลังปรับแล้วได้มูลค่าที่พอไหม
            final_notional = edt_quantity * current_price
            if final_notional < min_notional:
                # ถ้ายังไม่พอ ปรับเพิ่มอีก
                edt_quantity = float(Decimal(str(min_notional / current_price)).quantize(Decimal('1e-{}'.format(precision)), rounding=ROUND_UP))
            
            #message(symbol, f"ปรับปริมาณเพื่อให้ได้มูลค่าขั้นต่ำ {min_notional} USDT (ปริมาณ: {edt_quantity}, มูลค่า: {edt_quantity * current_price:.2f} USDT)", "yellow")
            
        elif edt_quantity == 0 or edt_quantity < min_quantity:
            edt_quantity = min_quantity
            # เช็คว่า min_quantity ให้มูลค่าพอไหม
            if min_quantity * current_price < min_notional:
                edt_quantity = float(Decimal(str(min_notional / current_price)).quantize(Decimal('1e-{}'.format(precision)), rounding=ROUND_UP))
            message(symbol, f"ปรับปริมาณเป็นค่าขั้นต่ำ: {edt_quantity} (มูลค่า: {edt_quantity * current_price:.2f} USDT)", "yellow")

        # เช็คครั้งสุดท้าย
        final_notional = edt_quantity * current_price
        if final_notional < min_notional:
            message(symbol, f"ไม่สามารถสร้าง Order ได้: มูลค่า ({final_notional:.2f} USDT) ต่ำกว่าขั้นต่ำ ({min_notional} USDT)", "red")
            return None

        return edt_quantity

    except Exception as e:
        message(symbol, f"เกิดข้อผิดพลาดในการปรับ quantity: {str(e)}", "red")
        return None
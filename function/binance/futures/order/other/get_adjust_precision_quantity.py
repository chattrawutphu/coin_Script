from decimal import ROUND_UP, Decimal, ROUND_DOWN, ROUND_HALF_UP
from function.binance.futures.order.other.get_future_market_price import get_future_market_price
from function.binance.futures.system.load_json_data import load_json_data
from function.message import message
from config import api_key, api_secret

def safe_decimal_conversion(value):
    """แปลงค่าให้เป็น Decimal อย่างปลอดภัย"""
    try:
        if isinstance(value, Decimal):
            return value
        if isinstance(value, (int, float)):
            return Decimal(str(value))
        if isinstance(value, str):
            # ทำความสะอาดข้อมูล
            clean_value = value.strip().replace(',', '')
            return Decimal(clean_value)
        return Decimal('0')
    except Exception as e:
        message("SYSTEM", f"Error converting to Decimal: {value} ({type(value)}), Error: {str(e)}", "red")
        raise

async def get_adjust_precision_quantity(symbol, quantity, current_price=None):
    """ปรับปริมาณการเทรดให้ตรงตามความละเอียดที่กำหนด"""
    try:
        # Debug logging
        #message(symbol, f"Adjusting quantity: {quantity} (type: {type(quantity)})", "debug")
        
        # โหลดข้อมูล symbol
        symbol_data = await load_json_data("json/symbol_precision.json")
        symbol_info = next((item for item in symbol_data if item["id"] == symbol), None)
        
        if not symbol_info:
            message(symbol, f"ไม่พบข้อมูล {symbol} ใน symbol_precision.json", "red")
            return None

        # ดึงค่าที่จำเป็น
        precision = int(symbol_info["precision"]["amount"])
        min_quantity = safe_decimal_conversion(symbol_info["limits"]["amount"]["min"])
        min_notional = Decimal('100')  # 100 USDT

        # ดึงราคาปัจจุบันถ้าไม่มี
        if not current_price:
            current_price = await get_future_market_price(api_key, api_secret, symbol)
            if not current_price:
                message(symbol, "ไม่สามารถดึงราคาตลาดได้", "red")
                return None
        
        # แปลงราคาเป็น Decimal
        current_price = safe_decimal_conversion(current_price)
        
        # แปลง quantity เป็น Decimal และปรับความละเอียด
        try:
            quantity_decimal = safe_decimal_conversion(quantity)
            precision_format = '1e-{}'.format(precision)
            edt_quantity = abs(quantity_decimal.quantize(Decimal(precision_format), rounding=ROUND_DOWN))
            
            #message(symbol, f"Initial adjusted quantity: {edt_quantity}", "debug")
            
        except Exception as e:
            message(symbol, f"Error in quantity conversion: {str(e)}", "red")
            return None

        # คำนวณมูลค่า order
        notional_value = edt_quantity * current_price
        
        # ปรับปริมาณตามเงื่อนไขขั้นต่ำ
        if notional_value < min_notional:
            min_qty_for_notional = min_notional / current_price
            edt_quantity = Decimal(str(max(float(min_quantity), float(min_qty_for_notional))))
            edt_quantity = edt_quantity.quantize(Decimal(precision_format), rounding=ROUND_UP)
            
            final_notional = edt_quantity * current_price
            if final_notional < min_notional:
                edt_quantity = (min_notional / current_price).quantize(Decimal(precision_format), rounding=ROUND_UP)
            
            """message(symbol, 
                f"Adjusted for min notional - Quantity: {edt_quantity}, "
                f"Value: {edt_quantity * current_price:.2f} USDT", "debug")"""
            
        elif edt_quantity == Decimal('0') or edt_quantity < min_quantity:
            edt_quantity = min_quantity
            if min_quantity * current_price < min_notional:
                edt_quantity = (min_notional / current_price).quantize(Decimal(precision_format), rounding=ROUND_UP)
            
            """message(symbol, 
                f"Adjusted for min quantity - Quantity: {edt_quantity}, "
                f"Value: {edt_quantity * current_price:.2f} USDT", "debug")"""

        # ตรวจสอบครั้งสุดท้าย
        final_notional = edt_quantity * current_price
        if final_notional < min_notional:
            message(symbol, 
                f"ไม่สามารถสร้าง Order ได้: มูลค่า ({final_notional:.2f} USDT) "
                f"ต่ำกว่าขั้นต่ำ ({min_notional} USDT)", "red")
            return None

        # แปลงกลับเป็น float สำหรับส่งคืน
        return float(edt_quantity)

    except Exception as e:
        message(symbol, f"เกิดข้อผิดพลาดในการปรับ quantity: {type(e).__name__}: {str(e)}", "red")
        return None
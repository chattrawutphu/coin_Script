import json
from decimal import Decimal, ROUND_DOWN, InvalidOperation
from function.message import message

def load_symbol_data():
    try:
        with open('json/symbol_precision.json', 'r') as file:
            return json.load(file)
    except Exception as e:
        message("SYSTEM", f"Error loading symbol data: {str(e)}", "red")
        return []

def get_adjust_precision_price(symbol, price):
    """ปรับความละเอียดของราคาตาม precision ของเหรียญ"""
    try:
        # ถ้า price เป็น string 'now' หรือ None
        if price == 'now' or price is None:
            return None

        # ทำให้แน่ใจว่า price เป็นตัวเลข
        try:
            if isinstance(price, str):
                # ลบ symbols ที่ไม่ต้องการออก (เช่น $)
                price = price.strip('$').strip()
            numeric_price = float(price)
        except (ValueError, TypeError):
            message(symbol, f"Invalid price format: {price}", "red")
            return None

        # โหลดข้อมูล symbol
        symbol_data = load_symbol_data()
        if not symbol_data:
            message(symbol, "No symbol data available", "red")
            return None

        # หา precision ของ symbol
        precision = next((item["precision"]["price"] for item in symbol_data if item["id"] == symbol), None)
        if precision is None:
            message(symbol, f"No precision data found for {symbol}", "red")
            return None

        # แปลงเป็น Decimal และปรับความละเอียด
        try:
            price_decimal = Decimal(str(numeric_price))
            adjusted_price = float(price_decimal.quantize(Decimal(f'1e-{precision}'), rounding=ROUND_DOWN))
            
            # ตรวจสอบว่าราคาที่ปรับแล้วเป็นค่าที่ถูกต้อง
            if adjusted_price <= 0:
                message(symbol, f"Adjusted price is invalid: {adjusted_price}", "red")
                return None
                
            return adjusted_price

        except InvalidOperation as e:
            message(symbol, f"Error adjusting price precision: {str(e)}", "red")
            return None

    except Exception as e:
        message(symbol, f"Error in price adjustment: {str(e)}", "red")
        return None
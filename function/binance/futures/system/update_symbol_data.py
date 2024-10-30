import json
import os
import traceback
from config import TRADING_CONFIG
from function.binance.futures.system.create_future_exchange import create_future_exchange
from function.message import message

async def update_symbol_data(api_key, api_secret):
    exchange = None
    try:
        exchange = await create_future_exchange(api_key, api_secret)
        
        # เพิ่ม await สำหรับ fetch_markets
        data = await exchange.fetch_markets()

        filtered_data = []
        for item in data:
            if item.get("info", {}).get("contractType") == "PERPETUAL":
                filtered_item = {
                    "id": item["id"],
                    "symbol": item["symbol"],
                    "base": item["base"],
                    "quote": item["quote"],
                    "precision": item["precision"],
                    "limits": item["limits"],
                    "info": {
                        "pricePrecision": item["info"]["pricePrecision"],
                        "quantityPrecision": item["info"]["quantityPrecision"],
                        "minQty": item["limits"]["amount"]["min"] if "amount" in item["limits"] else None,
                        "minNotional": 25  # Binance Future minimum notional value
                    }
                }
                filtered_data.append(filtered_item)

        # เขียนข้อมูลลงไฟล์
        with open('json/symbol_precision.json', 'w') as f:
            json.dump(filtered_data, f, indent=4)

        message("SYSTEM", f"อัพเดท symbol_data เรียบร้อย! จำนวน {len(filtered_data)} symbols", "green")
        
        return filtered_data

    except Exception as e:
        error_traceback = traceback.format_exc()
        message("SYSTEM", f"เกิดข้อผิดพลาดในการอัพเดท symbol_data: {str(e)}", "red")
        message("SYSTEM", f"Error: {error_traceback}", "red")
        return None
        
    finally:
        # ปิด exchange ใน finally block
        if exchange:
            try:
                await exchange.close()
            except Exception as e:
                message("MAIN", f"เกิดข้อผิดพลาดในการปิด exchange: {str(e)}", "red")
import traceback
import ccxt.async_support as ccxt
from function.binance.futures.system.create_future_exchange import create_future_exchange
from function.message import message

async def swap_position_side(api_key, api_secret, symbol):
    try:
        # สร้าง exchange object
        exchange = await create_future_exchange(api_key, api_secret)

        # ดึงข้อมูลตำแหน่งปัจจุบัน
        positions = await exchange.fetch_positions([symbol])

        eexchange_symbol = symbol
        if 'USDT' in symbol and '/USDT:USDT' not in symbol:
            exchange_symbol = symbol.replace("USDT", "/USDT:USDT")

        # Find the current position
        current_position = next((p for p in positions if p['symbol'] == exchange_symbol and p['contracts'] > 0), None)

        if current_position is None:
            print(f"ไม่พบตำแหน่งที่เปิดอยู่สำหรับ {symbol}")
            await exchange.close()
            return None

        # คำนวณขนาดตำแหน่งใหม่ (ใช้ค่าสัมบูรณ์เพื่อให้แน่ใจว่าเป็นค่าบวกเสมอ)
        size = abs(current_position['contracts'])
        
        # กำหนดทิศทางใหม่
        new_side = 'sell' if current_position['side'] == 'long' else 'buy'

        # สร้างคำสั่งปิดตำแหน่งเดิมและเปิดตำแหน่งใหม่พร้อมกัน
        order = await exchange.create_market_order(
            symbol,
            new_side,
            size * 2,  # ขนาดเป็น 2 เท่าเพื่อปิดตำแหน่งเดิมและเปิดตำแหน่งใหม่
            params={'reduceOnly': False}
        )

        await exchange.close()

        #print(f"เปลี่ยนตำแหน่งสำเร็จ: จาก {current_position['side']} เป็น {new_side}")
        return order

    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"เกิดข้อผิดพลาดในการเปลี่ยนตำแหน่ง: {str(e)}", "red")
        message(symbol, "________________________________", "red")
        message(symbol, f"Error: {error_traceback}", "red")
        message(symbol, "________________________________", "red")
        return None
    finally:
        await exchange.close()
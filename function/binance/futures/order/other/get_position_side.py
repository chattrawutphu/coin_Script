import ccxt.async_support as ccxt
from function.binance.futures.system.create_future_exchange import create_future_exchange

async def get_position_side(api_key, api_secret, symbol):
    try:
        # สร้าง exchange object
        exchange = await create_future_exchange(api_key, api_secret)

        # แปลง symbol เป็นรูปแบบที่ exchange ใช้
        exchange_symbol = symbol
        if 'USDT' in symbol and '/USDT:USDT' not in symbol:
            exchange_symbol = symbol.replace("USDT", "/USDT:USDT")

        # ดึงข้อมูลตำแหน่งทั้งหมด
        positions = await exchange.fetch_positions([exchange_symbol])

        # ปิด connection
        await exchange.close()

        # ตรวจสอบตำแหน่งที่เปิดอยู่
        for position in positions:
            # ตรวจสอบทั้งรูปแบบ symbol ที่ใช้เรียกฟังก์ชันและรูปแบบที่ exchange ใช้
            if (position['symbol'] == symbol or position['symbol'] == exchange_symbol) and float(position['contracts']) > 0:
                # ถ้ามีตำแหน่งที่เปิดอยู่ ตรวจสอบทิศทาง
                if position['side'] == 'long':
                    return 'buy'
                elif position['side'] == 'short':
                    return 'sell'

        # ถ้าไม่มีตำแหน่งที่เปิดอยู่
        return None

    except Exception as e:
        print(f"เกิดข้อผิดพลาดในการดึงข้อมูลตำแหน่ง: {e}")
        return None
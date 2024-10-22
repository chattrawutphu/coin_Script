import ccxt.async_support as ccxt
from function.binance.futures.system.create_future_exchange import create_future_exchange

async def change_stoploss_to_price(api_key, api_secret, symbol, new_stoploss_price):
    try:
        # สร้าง exchange object
        exchange = await create_future_exchange(api_key, api_secret)

        # ดึงข้อมูลตำแหน่งปัจจุบัน
        positions = await exchange.fetch_positions([symbol])

        # Convert input symbol to the format used by the exchange
        exchange_symbol = symbol.replace("USDT", "/USDT:USDT")

        # Find the current position
        current_position = next((p for p in positions if p['symbol'] == exchange_symbol and p['contracts'] > 0), None)

        if current_position is None:
            print(f"ไม่พบตำแหน่งที่เปิดอยู่สำหรับ {symbol}")
            await exchange.close()
            return None

        # Process the current_position as needed

        # ดึงคำสั่ง stop loss ที่มีอยู่
        open_orders = await exchange.fetch_open_orders(symbol)
        existing_stoploss = next((order for order in open_orders if order['type'].lower() == 'stop' or order['type'].lower() == 'stop_market'), None)

        # ถ้ามีคำสั่ง stop loss อยู่แล้ว ให้ยกเลิกก่อน
        if existing_stoploss:
            await exchange.cancel_order(existing_stoploss['id'], symbol)
            print(f"ยกเลิกคำสั่ง stop loss เดิม: {existing_stoploss['id']}")

        # สร้างคำสั่ง stop loss ใหม่
        side = 'sell' if current_position['side'] == 'long' else 'buy'
        amount = abs(current_position['contracts'])
        
        new_stoploss_order = await exchange.create_order(
            symbol,
            'stop_market',
            side,
            amount,
            new_stoploss_price,
            {'stopPrice': new_stoploss_price, 'reduceOnly': True}
        )

        await exchange.close()

        print(f"สร้างคำสั่ง stop loss ใหม่ที่ราคา {new_stoploss_price}")
        return new_stoploss_order

    except Exception as e:
        print(f"เกิดข้อผิดพลาดในการเปลี่ยน stop loss: {e}")
        await exchange.close()
        return None
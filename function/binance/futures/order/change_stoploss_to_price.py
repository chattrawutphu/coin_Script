import traceback
import ccxt.async_support as ccxt
from function.binance.futures.order.get_all_order import clear_stoploss
from function.binance.futures.system.create_future_exchange import create_future_exchange
from function.message import message

async def change_stoploss_to_price(api_key, api_secret, symbol, new_stoploss_price):
    exchange = None
    try:
        exchange = await create_future_exchange(api_key, api_secret)

        await clear_stoploss(api_key, api_secret, symbol)
        positions = await exchange.fetch_positions([symbol])
        exchange_symbol = symbol
        if 'USDT' in symbol and '/USDT:USDT' not in symbol:
            exchange_symbol = symbol.replace("USDT", "/USDT:USDT")

        current_position = next((p for p in positions 
            if p['symbol'] == exchange_symbol and abs(float(p['contracts'])) > 0), None)

        if current_position is None:
            message(symbol, f"ไม่พบตำแหน่งที่เปิดอยู่สำหรับ {symbol}", "yellow")
            return None

        # สร้างคำสั่ง stop loss ใหม่
        side = 'sell' if current_position['side'] == 'long' else 'buy'
        amount = abs(float(current_position['contracts']))
        
        # สร้าง stop loss ใหม่
        new_stoploss_order = await exchange.create_order(
            symbol,
            'stop_market',
            side,
            amount,
            None,
            {'stopPrice': new_stoploss_price, 'reduceOnly': True}
        )
        
        message(symbol, f"สร้างคำสั่ง stop loss ใหม่ที่ราคา {new_stoploss_price}")

        # ถ้าสร้าง stop loss ใหม่สำเร็จ ค่อยยกเลิกคำสั่งเดิม
        open_orders = await exchange.fetch_open_orders(symbol)
        for order in open_orders:
            if order['type'].lower() == 'stop_market' and order['id'] != new_stoploss_order['id']:
                await exchange.cancel_order(order['id'], symbol)
                #message(symbol, f"ยกเลิกคำสั่ง stop loss เดิม: {order['id']}")

        return new_stoploss_order

    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"เกิดข้อผิดพลาดในการตั้ง Stop Loss: {str(e)}", "red")
        message(symbol, "________________________________", "red")
        message(symbol, f"Error: {error_traceback}", "red")
        message(symbol, "________________________________", "red")
        return None
    finally:
        if exchange:
            await exchange.close()
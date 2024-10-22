import asyncio
from datetime import datetime
import json
import os
import time
import traceback

import pytz

from function.binance.futures.check.check_future_available_balance import check_future_available_balance
from function.binance.futures.check.check_position import check_position
from function.binance.futures.check.check_price import check_price
from function.binance.futures.check.check_server_status import check_server_status
from function.binance.futures.check.check_user_api_status import check_user_api_status
from function.binance.futures.get.get_rsi_cross_last_candle import get_rsi_cross_last_candle
from function.binance.futures.get.get_wait_candle_end import get_wait_candle_end
from function.binance.futures.order.change_stoploss_to_price import change_stoploss_to_price
from function.binance.futures.order.create_order import create_order
from function.binance.futures.order.get_all_order import clear_all_orders, get_all_order
from function.binance.futures.order.other.get_closed_position import get_amount_of_closed_position, get_closed_position_side
from function.binance.futures.order.other.get_future_market_price import get_future_market_price
from function.binance.futures.order.other.get_position_side import get_position_side
from function.binance.futures.order.swap_position_side import swap_position_side
from function.binance.futures.system.create_future_exchange import create_future_exchange
from function.codelog import codelog
from function.message import message

api_key = 'cos73h05s3oxvSK2u7YG2k0mIiu5npSVIXTdyIXXUVNJQOKbRybPNlGOeZNvunVG'
api_secret = 'Zim1iiECBaYdtx3rVlN5mpQ05iQWRXDXU0EBW8LmQW8Ns2X07HhKfIs4Kj3PLzgO'

last_candle_time = None
last_candle_cross = None
last_focus_price = None
last_focus_stopprice = None
is_wait_candle = False
is_in_position = False
is_swapping = False
isTry_last_entry = False
entry_candle = None
entry_price = None
entry_side = None
entry_stoploss_price = None

STATE_FILE = 'bot_state.json'
TRADE_RECORD_FILE = 'trade_records.json'
PRICE_CHANGE_THRESHOLD = 0.0001  # 0.1%
PRICE_INCREASE = 1 + PRICE_CHANGE_THRESHOLD  # 1.001
PRICE_DECREASE = 1 - PRICE_CHANGE_THRESHOLD  # 0.999
PRICE_CHANGE_MAXPERCENT = 5
ENTRY_AMOUNT = '25$'
MAX_CANDLES_TO_FETCH = 5
MIN_CANDLES_TO_FETCH = 3

# ฟังก์ชันสำหรับบันทึกและโหลดสถานะ
def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return None

# ฟังก์ชันสำหรับบันทึกผลการเทรด
async def record_trade(api_key, api_secret, symbol, action, entry_price, exit_price, amount, reason):
    try:
        with open(TRADE_RECORD_FILE, 'r') as f:
            trades = json.load(f)
    except FileNotFoundError:
        trades = []

    if action in ['BUY', 'SELL']:
        profit_loss = (exit_price - entry_price) * amount if action == 'BUY' else (entry_price - exit_price) * amount
    elif action == 'SWAP':
        profit_loss = (exit_price - entry_price) * amount if exit_price > entry_price else (entry_price - exit_price) * amount
    else:
        profit_loss = 0

    trade = {
        'timestamp': datetime.now().isoformat(),
        'symbol': symbol,
        'action': action,
        'entry_price': entry_price,
        'exit_price': exit_price,
        'amount': amount,
        'profit_loss': profit_loss,
        'profit_loss_percentage': (profit_loss / (entry_price * amount)) * 100 if entry_price and amount else 0,
        'reason': reason
    }

    trades.append(trade)

    with open(TRADE_RECORD_FILE, 'w') as f:
        json.dump(trades, f, indent=2)

    message(symbol, f"บันทึกการเทรด: {action} {symbol} ที่ราคา {exit_price:.2f}", "cyan")

# ฟังก์ชันหลักสำหรับตรวจสอบแท่งเทียนใหม่และ RSI
async def check_new_candle_and_rsi(api_key, api_secret, symbol, timeframe):
    # โหลดสถานะเดิม (ถ้ามี)
    saved_state = load_state()
    last_candle_time = saved_state.get('last_candle_time')
    if last_candle_time:
        last_candle_time = datetime.fromisoformat(last_candle_time)
    if saved_state:
        message(symbol, "System Startup - Loading saved state", "cyan")
        
        last_candle_time = saved_state.get('last_candle_time')
        if last_candle_time:
            last_candle_time = datetime.fromisoformat(last_candle_time)
        message(symbol, f"last_candle_time: {last_candle_time}", "blue")
        
        last_candle_cross = saved_state.get('last_candle_cross')
        message(symbol, f"last_candle_cross: {last_candle_cross}", "blue")
        
        last_focus_price = saved_state.get('last_focus_price')
        message(symbol, f"last_focus_price: {last_focus_price}", "blue")
        
        last_focus_stopprice = saved_state.get('last_focus_stopprice')
        message(symbol, f"last_focus_stopprice: {last_focus_stopprice}", "blue")
        
        is_wait_candle = saved_state.get('is_wait_candle', False)
        message(symbol, f"is_wait_candle: {is_wait_candle}", "blue")
        
        is_in_position = saved_state.get('is_in_position', False)
        message(symbol, f"is_in_position: {is_in_position}", "blue")
        
        is_swapping = saved_state.get('is_swapping', False)
        message(symbol, f"is_swapping: {is_swapping}", "blue")
        
        isTry_last_entry = saved_state.get('isTry_last_entry', False)
        message(symbol, f"isTry_last_entry: {isTry_last_entry}", "blue")
        
        entry_candle = saved_state.get('entry_candle')
        message(symbol, f"entry_candle: {entry_candle}", "blue")
        
        entry_price = saved_state.get('entry_price')
        message(symbol, f"entry_price: {entry_price}", "blue")
        
        entry_side = saved_state.get('entry_side')
        message(symbol, f"entry_side: {entry_side}", "blue")
        
        entry_stoploss_price = saved_state.get('entry_stoploss_price')
        message(symbol, f"entry_stoploss_price: {entry_stoploss_price}", "blue")

        message(symbol, "Saved state loaded successfully", "green")
    else:
        message(symbol, "No saved state found. Starting with default values", "yellow")
        # Initialize variables with default values here
        last_candle_time = None
        last_candle_cross = None
        last_focus_price = None
        last_focus_stopprice = None
        is_wait_candle = False
        is_in_position = False
        is_swapping = False
        isTry_last_entry = False
        entry_candle = None
        entry_price = None
        entry_side = None
        entry_stoploss_price = None
    
    exchange = await create_future_exchange(api_key, api_secret)

    is_in_position = await check_position(api_key, api_secret, symbol)
    message(symbol, f"สถานะ position : {'มี' if is_in_position else 'ไม่มี'}")

    while True:
        try:
            price = await get_future_market_price(api_key, api_secret, symbol)
            if price is None:
                message(symbol, "ไม่สามารถดึงราคาตลาดได้ ข้ามรอบนี้", "yellow")
                await asyncio.sleep(1)
                continue

            if is_wait_candle:
                side = await get_position_side(api_key, api_secret, symbol)
                if side == 'buy':
                    if price > last_candle_cross['candle']['high'] * PRICE_INCREASE:
                        new_stoploss = last_candle_cross['candle']['low'] * PRICE_DECREASE
                        await change_stoploss_to_price(api_key, api_secret, symbol, new_stoploss)
                        message(symbol, f"ปรับ Stop Loss เป็น {new_stoploss:.8f}", "cyan")
                        is_wait_candle = False
                elif side == 'sell':
                    if price < last_candle_cross['candle']['low'] * PRICE_DECREASE:
                        new_stoploss = last_candle_cross['candle']['high'] * PRICE_INCREASE
                        await change_stoploss_to_price(api_key, api_secret, symbol, new_stoploss)
                        message(symbol, f"ปรับ Stop Loss เป็น {new_stoploss:.8f}", "cyan")
                        is_wait_candle = False

            if isTry_last_entry:
                current_time = datetime.now(pytz.UTC)
                if last_candle_cross and 'candle' in last_candle_cross and 'time' in last_candle_cross['candle']:
                    last_cross_time = datetime.strptime(last_candle_cross['candle']['time'], '%d/%m/%Y %H:%M').replace(tzinfo=pytz.UTC)
                    time_difference = current_time - last_cross_time
                    candles_passed = time_difference.total_seconds() / (timeframe_to_seconds(timeframe))

                    ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, since=int(last_cross_time.timestamp() * 1000))
                    
                    if ohlcv:
                        if last_candle_cross['type'] == 'crossunder':
                            lowest_price = min(candle[3] for candle in ohlcv)  # Find lowest low
                            reference_price = last_candle_cross['candle'].get('low')
                            if reference_price is not None:
                                price_change_percent = (lowest_price - reference_price) / reference_price * 100
                            else:
                                message(symbol, "ไม่พบราคาอ้างอิง (ต่ำสุด) ข้ามการคำนวณการเปลี่ยนแปลงราคา", "yellow")
                                continue
                        else:  # crossover
                            highest_price = max(candle[2] for candle in ohlcv)  # Find highest high
                            reference_price = last_candle_cross['candle'].get('high')
                            if reference_price is not None:
                                price_change_percent = (highest_price - reference_price) / reference_price * 100
                            else:
                                message(symbol, "ไม่พบราคาอ้างอิง (สูงสุด) ข้ามการคำนวณการเปลี่ยนแปลงราคา", "yellow")
                                continue

                        if candles_passed <= 5 and abs(price_change_percent) < PRICE_CHANGE_MAXPERCENT:
                            closed_position_amount = await get_amount_of_closed_position(api_key, api_secret, symbol)
                            if closed_position_amount is not None:
                                if last_candle_cross['type'] == 'crossover':
                                    if price > last_candle_cross['candle'].get('low', 0) * PRICE_DECREASE and price < (last_candle_cross['candle'].get('high', 0) * PRICE_INCREASE) * 1.02:
                                        await create_order(api_key, api_secret, symbol=symbol, side='buy', price='now', quantity=abs(closed_position_amount), order_type='market')
                                        await create_order(api_key, api_secret, symbol=symbol, side='sell', price=str(last_candle_cross['candle'].get('low', 0) * PRICE_DECREASE), quantity='MAX', order_type='STOPLOSS_MARKET')
                                        isTry_last_entry = False
                                        message(symbol, "เข้า Long ตามสัญญาณ Crossover สำเร็จ", "green")
                                        await record_trade(api_key, api_secret, symbol, 'BUY', price, None, abs(closed_position_amount), 'Enter Long Position')
                                else:
                                    if price < last_candle_cross['candle'].get('high', 0) * PRICE_INCREASE and price > (last_candle_cross['candle'].get('low', 0) * PRICE_DECREASE) * 1.02:
                                        await create_order(api_key, api_secret, symbol=symbol, side='sell', price='now', quantity=abs(closed_position_amount), order_type='market')
                                        await create_order(api_key, api_secret, symbol=symbol, side='buy', price=str(last_candle_cross['candle'].get('high', 0) * PRICE_INCREASE), quantity='MAX', order_type='STOPLOSS_MARKET')
                                        isTry_last_entry = False
                                        message(symbol, "เข้า Short ตามสัญญาณ Crossunder สำเร็จ", "green")
                                        await record_trade(api_key, api_secret, symbol, 'SELL', price, None, abs(closed_position_amount), 'Enter Short Position')
                            else:
                                message(symbol, "ไม่สามารถดึงข้อมูลปริมาณ position ที่ปิดได้ ข้ามการสร้างคำสั่งซื้อขาย", "yellow")
                    else:
                        message(symbol, "ไม่มีข้อมูล OHLCV ข้ามรอบนี้", "yellow")
                else:
                    message(symbol, "ข้อมูล last_candle_cross ไม่ถูกต้อง ข้ามรอบนี้", "yellow")
                    isTry_last_entry = False

            if is_in_position and not is_swapping and not await check_position(api_key, api_secret, symbol):
                await clear_all_orders(api_key, api_secret, symbol)
                message(symbol, ' position ถูกปิดแล้ว!', "magenta")
                
                # บันทึกการออกจาก position
                exit_price = await get_future_market_price(api_key, api_secret, symbol)
                await record_trade(api_key, api_secret, symbol, 'SELL' if entry_side == 'buy' else 'BUY', entry_price, exit_price, ENTRY_AMOUNT, 'Position Closed')
                
                is_in_position = False
                if is_wait_candle:
                    closed_position_amount = await get_amount_of_closed_position(api_key, api_secret, symbol)
                    closed_position_side = await get_closed_position_side(api_key, api_secret, symbol)
                    
                    if closed_position_side == 'buy':
                        new_entry_side = 'sell'
                        new_entry_price = price
                        new_stoploss_price = last_candle_cross['candle']['high'] * PRICE_INCREASE
                    else:
                        new_entry_side = 'buy'
                        new_entry_price = price
                        new_stoploss_price = last_candle_cross['candle']['low'] * PRICE_DECREASE

                    await create_order(api_key, api_secret, symbol=symbol, side=new_entry_side, price='now', quantity=abs(closed_position_amount), order_type='market')
                    await create_order(api_key, api_secret, symbol=symbol, side=('sell' if new_entry_side=='buy' else 'buy'), price=str(new_stoploss_price), quantity='MAX', order_type='STOPLOSS_MARKET')
                    
                    message(symbol, f"เข้า position {new_entry_side} ตรงข้ามสำเร็จ ขนาด: {abs(closed_position_amount):.8f}, Stoploss: {new_stoploss_price:.8f}", "green")
                    await record_trade(api_key, api_secret, symbol, new_entry_side.upper(), new_entry_price, None, abs(closed_position_amount), 'Enter Opposite Position')
                    is_in_position = True
                    is_wait_candle = False
                else:
                    isTry_last_entry = True
            
            if last_focus_price is not None:
                side = await get_position_side(api_key, api_secret, symbol)
                if side == 'buy':
                    if price < last_focus_price * PRICE_DECREASE:
                        is_swapping = True
                        await swap_position_side(api_key, api_secret, symbol)
                        await clear_all_orders(api_key, api_secret, symbol)
                        await create_order(api_key, api_secret, symbol=symbol, side='buy', price=str(last_candle_cross['candle']['high'] * PRICE_INCREASE), quantity='MAX', order_type='STOPLOSS_MARKET')
                        message(symbol, f"สลับ position จาก {side}", "magenta")
                        
                        # บันทึกการ swap
                        await record_trade(api_key, api_secret, symbol, 'SWAP', last_focus_price, price, ENTRY_AMOUNT, 'Position Swap')
                        
                        is_swapping = False
                        last_focus_price = None
                        entry_stoploss_price = None
                    elif price > last_focus_stopprice * PRICE_INCREASE:
                        await change_stoploss_to_price(api_key, api_secret, symbol, last_focus_price)
                        message(symbol, f"ปรับ Stop Loss เป็น {last_focus_price:.8f}", "cyan")
                        last_focus_price = None
                        entry_stoploss_price = None
                elif side == 'sell':
                    if price > last_focus_price * PRICE_INCREASE:
                        is_swapping = True
                        await swap_position_side(api_key, api_secret, symbol)
                        await clear_all_orders(api_key, api_secret, symbol)
                        await create_order(api_key, api_secret, symbol=symbol, side='sell', price=str(last_candle_cross['candle']['low'] * PRICE_DECREASE), quantity='MAX', order_type='STOPLOSS_MARKET')
                        message(symbol, f"สลับ position จาก {side}", "magenta")
                        
                        # บันทึกการ swap
                        await record_trade(api_key, api_secret, symbol, 'SWAP', last_focus_price, price, ENTRY_AMOUNT, 'Position Swap')
                        
                        is_swapping = False
                        last_focus_price = None
                        entry_stoploss_price = None
                    elif price < last_focus_stopprice * PRICE_DECREASE:
                        await change_stoploss_to_price(api_key, api_secret, symbol, last_focus_price)
                        message(symbol, f"ปรับ Stop Loss เป็น {last_focus_price:.8f}", "cyan")
                        last_focus_price = None
                        entry_stoploss_price = None
            
            if entry_price is not None:
                if entry_side == 'buy':
                    if price > entry_price * PRICE_INCREASE:
                        await create_order(api_key, api_secret, symbol=symbol, side=entry_side, price='now', quantity=ENTRY_AMOUNT, order_type='market')
                        await create_order(api_key, api_secret, symbol=symbol, side='sell', price=str(entry_stoploss_price * PRICE_DECREASE), quantity='MAX', order_type='STOPLOSS_MARKET')
                        message(symbol, 'เข้า Long position สำเร็จ', "green")
                        
                        # บันทึกการเข้า position
                        await record_trade(api_key, api_secret, symbol, 'BUY', entry_price, price, ENTRY_AMOUNT, 'Enter Long Position')
                        
                        is_in_position = True
                        entry_candle = await get_current_candle(api_key, api_secret, symbol, timeframe)
                        entry_price = None
                        entry_stoploss_price = None
                        entry_side = None
                    elif price < entry_stoploss_price * PRICE_DECREASE:
                        message(symbol, 'ยกเลิก Long entry', "yellow")
                        entry_price = None
                        entry_stoploss_price = None
                        entry_side = None
                    else:
                        message(symbol, f'รอราคาทะลุ {entry_price:.8f} เพื่อ Long', "blue")
                elif entry_side == 'sell':
                    if price < entry_price * PRICE_DECREASE:
                        await create_order(api_key, api_secret, symbol=symbol, side=entry_side, price='now', quantity=ENTRY_AMOUNT, order_type='market')
                        await create_order(api_key, api_secret, symbol=symbol, side='buy', price=str(entry_stoploss_price * PRICE_INCREASE), quantity='MAX', order_type='STOPLOSS_MARKET')
                        message(symbol, 'เข้า Short position สำเร็จ', "green")
                        
                        # บันทึกการเข้า position
                        await record_trade(api_key, api_secret, symbol, 'SELL', entry_price, price, ENTRY_AMOUNT, 'Enter Short Position')
                        
                        is_in_position = True
                        entry_candle = await get_current_candle(api_key, api_secret, symbol, timeframe)
                        entry_price = None
                        entry_stoploss_price = None
                        entry_side = None
                    elif price > entry_stoploss_price * PRICE_INCREASE:
                        message(symbol, 'ยกเลิก Short entry', "yellow")
                        entry_price = None
                        entry_stoploss_price = None
                        entry_side = None
                    else:
                        message(symbol, f'รอราคาทะลุ {entry_price:.8f} เพื่อ Short', "blue")

            ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, limit=1)
            
            if ohlcv and len(ohlcv) > 0:
                current_candle_time = datetime.fromtimestamp(ohlcv[0][0] / 1000, tz=pytz.UTC)
                
                # Check for new candle
                if last_candle_time is None or current_candle_time > last_candle_time:
                    last_candle_time = current_candle_time
                    side = await get_position_side(api_key, api_secret, symbol)

                    if is_in_position and entry_candle:
                        current_candle = await get_current_candle(api_key, api_secret, symbol, timeframe)
                        if current_candle:
                            time_since_entry = current_candle['timestamp'] - entry_candle['timestamp']
                            candles_since_entry = (time_since_entry // get_timeframe_milliseconds(timeframe))
                            
                            if candles_since_entry >= 4:  # ต้องมีอย่างน้อย 3 แท่งที่ปิดแล้ว + แท่งปัจจุบัน
                                position_side = await get_position_side(api_key, api_secret, symbol)
                                if position_side:
                                    current_stoploss = await get_current_stoploss(api_key, api_secret, symbol)
                                    new_stoploss = await adjust_stoploss(api_key, api_secret, symbol, timeframe, position_side, entry_candle['timestamp'], current_stoploss)
                                    if new_stoploss:
                                        message(symbol, f"ปรับ Stoploss เป็น {new_stoploss:.8f} (Three Candle Rule)", "cyan")
                                else:
                                    message(symbol, "ไม่สามารถดึงข้อมูลด้านของ position ข้ามการปรับ Stoploss", "yellow")
                            else:
                                message(symbol, f"รอให้ครบ 3 แท่งที่ปิดแล้วก่อนปรับ Stoploss อีก {4 - candles_since_entry} แท่งเทียน", "blue")
                        else:
                            message(symbol, "ไม่สามารถดึงข้อมูลแท่งเทียนปัจจุบัน ข้ามการปรับ Stoploss", "yellow")
                    
                    if is_wait_candle and side is not None:
                        is_wait_candle = False
                        if last_candle_cross and 'candle' in last_candle_cross:
                            last_focus_price = min(last_candle_cross['candle'].get('low', 0), ohlcv[0][3]) if side == 'buy' else max(last_candle_cross['candle'].get('high', 0), ohlcv[0][2])
                            last_focus_stopprice = max(last_candle_cross['candle'].get('high', 0), ohlcv[0][2]) if side == 'buy' else min(last_candle_cross['candle'].get('low', 0), ohlcv[0][3])
                            message(symbol, 'ปิดแท่งเทียนหลังเจอสัญญาณตรงกันข้าม! รอดูว่าจะสลับ position หรือขยับ Stoploss', "yellow")

                    # Check for RSI cross
                    isRsiCross = await get_rsi_cross_last_candle(api_key, api_secret, symbol, timeframe, 7, 32, 68)
                    if isRsiCross and 'status' in isRsiCross:
                        if isRsiCross.get('type') is not None:
                            message(symbol, f"ผลการตรวจสอบ RSI Cross: {isRsiCross}", "blue")
                        
                        if isRsiCross['status']:
                            if is_in_position and side is not None:
                                message(symbol, f"ทิศทางปัจจุบัน = {side} // ประเภท RSI Cross = {isRsiCross['type']}", "blue")
                                if (side == 'buy' and isRsiCross['type'] == 'crossunder') or (side == 'sell' and isRsiCross['type'] == 'crossover'):
                                    last_candle_cross = isRsiCross
                                    last_focus_price = None
                                    last_focus_stopprice = None
                                    is_wait_candle = True
                                    message(symbol, 'พบสัญญาณตรงกันข้าม! รอปิดแท่งเทียน!', "yellow")
                                else:
                                    await change_stoploss_to_price(api_key, api_secret, symbol, last_focus_price)
                                    message(symbol, f"ปรับ Stop Loss เป็น {last_focus_price:.8f}", "cyan")
                                    last_focus_price = None
                            elif not is_in_position:
                                await clear_all_orders(api_key, api_secret, symbol)
                                if 'candle' in isRsiCross:
                                    entry_price = isRsiCross['candle'].get('high') if isRsiCross['type'] == 'crossover' else isRsiCross['candle'].get('low')
                                    entry_stoploss_price = isRsiCross['candle'].get('low') if isRsiCross['type'] == 'crossover' else isRsiCross['candle'].get('high')
                                    entry_side = 'buy' if isRsiCross['type'] == 'crossover' else 'sell'
                                    message(symbol, f"ตั้งค่าการเข้า position : {entry_side} ที่ราคา {entry_price:.8f}, Stoploss ที่ {entry_stoploss_price:.8f}", "blue")
                    else:
                        message(symbol, "ข้อมูล RSI Cross ไม่ถูกต้อง ข้ามรอบนี้", "yellow")
            
            # บันทึกสถานะหลังจากการทำงานในแต่ละรอบ
            current_state = {
                'last_candle_time': last_candle_time.isoformat() if last_candle_time else None,
                'last_candle_cross': last_candle_cross,
                'last_focus_price': last_focus_price,
                'last_focus_stopprice': last_focus_stopprice,
                'is_wait_candle': is_wait_candle,
                'is_in_position': is_in_position,
                'is_swapping': is_swapping,
                'isTry_last_entry': isTry_last_entry,
                'entry_candle': entry_candle,
                'entry_price': entry_price,
                'entry_side': entry_side,
                'entry_stoploss_price': entry_stoploss_price
            }
            save_state(current_state)
            await asyncio.sleep(1)  # ปรับตามความเหมาะสม

        except Exception as e:
            error_traceback = traceback.format_exc()
            message(symbol, f"เกิดข้อผิดพลาด: {str(e)}", "red")
            message(symbol, "________________________________", "red")
            print(f"Error: {error_traceback}")
            message(symbol, "________________________________", "red")
            await asyncio.sleep(1)  # รอก่อนที่จะลองใหม่

async def get_current_stoploss(api_key, api_secret, symbol):
    # ฟังก์ชันนี้ควรดึงค่า stoploss ปัจจุบันจาก exchange
    # ตัวอย่างการใช้งาน (คุณอาจต้องปรับให้เข้ากับ API ของ exchange ที่คุณใช้)
    exchange = await create_future_exchange(api_key, api_secret)
    try:
        position = await exchange.fetch_positions([symbol])
        if position and len(position) > 0:
            return position[0]['stopPrice']
    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"ไม่สามารถดึงค่า stoploss ปัจจุบัน: {str(e)}", "red")
        message(symbol, "________________________________", "red")
        print(f"Error: {error_traceback}")
        message(symbol, "________________________________", "red")
        
    return None

async def adjust_stoploss(api_key, api_secret, symbol, timeframe, position_side, entry_time, current_stoploss):
    exchange = await create_future_exchange(api_key, api_secret)
    
    try:
        current_time = int(time.time() * 1000)
        
        if isinstance(entry_time, datetime):
            entry_timestamp = int(entry_time.timestamp() * 1000)
        else:
            entry_timestamp = entry_time
        
        candles_since_entry = (current_time - entry_timestamp) // get_timeframe_milliseconds(timeframe)
        candles_to_fetch = min(max(candles_since_entry, 3), 5)
        
        ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, limit=candles_to_fetch + 1)
        await exchange.close()
        
        if not ohlcv or len(ohlcv) < 2:
            message(symbol, "ไม่มีข้อมูล OHLCV เพียงพอ ข้ามการปรับ Stoploss", "yellow")
            return None
        
        closed_candles = ohlcv[:-1]
        
        if position_side == 'buy':
            prices = [candle[3] for candle in closed_candles]  # ราคาต่ำสุด
        elif position_side == 'sell':
            prices = [candle[2] for candle in closed_candles]  # ราคาสูงสุด
        else:
            raise ValueError("ทิศทาง position ไม่ถูกต้อง ต้องเป็น 'buy' หรือ 'sell' เท่านั้น")

        new_stoploss = None
        considered_candles = []

        for i in range(len(prices) - 2):
            for j in range(i + 1, len(prices) - 1):
                for k in range(j + 1, len(prices)):
                    if position_side == 'buy' and prices[i] < prices[j] < prices[k]:
                        new_stoploss = prices[j]
                        considered_candles = [prices[i], prices[j], prices[k]]
                        break
                    elif position_side == 'sell' and prices[i] > prices[j] > prices[k]:
                        new_stoploss = prices[j]
                        considered_candles = [prices[i], prices[j], prices[k]]
                        break
                if new_stoploss:
                    break
            if new_stoploss:
                break

        if new_stoploss is None:
            new_stoploss = min(prices) if position_side == 'buy' else max(prices)
            considered_candles = prices

        # ตรวจสอบเงื่อนไขเพิ่มเติม
        if position_side == 'buy' and new_stoploss <= current_stoploss:
            message(symbol, f"ไม่ปรับ Stoploss เนื่องจาก Stoploss ใหม่ ({new_stoploss:.2f}) ไม่สูงกว่า Stoploss ปัจจุบัน ({current_stoploss:.2f})", "yellow")
            return None
        elif position_side == 'sell' and new_stoploss >= current_stoploss:
            message(symbol, f"ไม่ปรับ Stoploss เนื่องจาก Stoploss ใหม่ ({new_stoploss:.2f}) ไม่ต่ำกว่า Stoploss ปัจจุบัน ({current_stoploss:.2f})", "yellow")
            return None

        # ปรับ Stoploss
        await change_stoploss_to_price(api_key, api_secret, symbol, new_stoploss)
        candles_str = ', '.join([f"{price:.2f}" for price in considered_candles])
        message(symbol, f"ปรับ Stoploss จาก {current_stoploss:.2f} เป็น {new_stoploss:.2f} (พิจารณาจากแท่งที่ปิดแล้วเท่านั้น {candles_str})", "cyan")

        return new_stoploss

    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"เกิดข้อผิดพลาดขณะปรับ Stoploss: {str(e)}", "red")
        message(symbol, "________________________________", "red")
        print(f"Error: {error_traceback}")
        message(symbol, "________________________________", "red")

        return None

def timeframe_to_seconds(timeframe):
    unit = timeframe[-1]
    value = int(timeframe[:-1])
    if unit == 'm':
        return value * 60
    elif unit == 'h':
        return value * 3600
    elif unit == 'd':
        return value * 86400
    else:
        raise ValueError(f"ไม่รองรับ Timeframe: {timeframe}")
    
def get_timeframe_milliseconds(timeframe):
    unit = timeframe[-1]
    value = int(timeframe[:-1])
    if unit == 'm':
        return value * 60 * 1000
    elif unit == 'h':
        return value * 60 * 60 * 1000
    elif unit == 'd':
        return value * 24 * 60 * 60 * 1000
    else:
        raise ValueError(f"ไม่รองรับ Timeframe: {timeframe}")
    
async def get_current_candle(api_key, api_secret, symbol, timeframe):
    exchange = await create_future_exchange(api_key, api_secret)
    try:
        ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, limit=1)
        await exchange.close()
        if ohlcv and len(ohlcv) > 0:
            return {
                'timestamp': ohlcv[0][0],
                'open': ohlcv[0][1],
                'high': ohlcv[0][2],
                'low': ohlcv[0][3],
                'close': ohlcv[0][4],
                'volume': ohlcv[0][5]
            }
    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"เกิดข้อผิดพลาดขณะดึงข้อมูลแท่งเทียนปัจจุบัน: {str(e)}", "red")
        message(symbol, "________________________________", "red")
        print(f"Error: {error_traceback}")
        message(symbol, "________________________________", "red")
    return None

async def main():
    try:
        symbol = 'ETHUSDT'
        timeframe = '3m'
        await check_new_candle_and_rsi(api_key, api_secret, symbol, timeframe)
    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol,f"พบข้อผิดพลาด", "yellow")
        message(symbol, "________________________________", "red")
        print(f"Error: {error_traceback}")
        message(symbol, "________________________________", "red")
    finally:
        # บันทึกสถานะก่อนจบการทำงาน
        current_state = {
            'last_candle_time': last_candle_time.isoformat() if last_candle_time else None,
            'last_candle_cross': last_candle_cross,
            'last_focus_price': last_focus_price,
            'last_focus_stopprice': last_focus_stopprice,
            'is_wait_candle': is_wait_candle,
            'is_in_position': is_in_position,
            'is_swapping': is_swapping,
            'isTry_last_entry': isTry_last_entry,
            'entry_candle': entry_candle,
            'entry_price': entry_price,
            'entry_side': entry_side,
            'entry_stoploss_price': entry_stoploss_price
        }
        save_state(current_state)

if __name__ == "__main__":
    asyncio.run(main())
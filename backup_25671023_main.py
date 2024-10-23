import asyncio
from datetime import datetime
import json
import os
import time
import traceback
from functools import wraps
import pytz

from function.binance.futures.check.check_position import check_position
from function.binance.futures.get.get_rsi_cross_last_candle import get_rsi_cross_last_candle
from function.binance.futures.order.change_stoploss_to_price import change_stoploss_to_price
from function.binance.futures.order.create_order import create_order
from function.binance.futures.order.get_all_order import clear_all_orders
from function.binance.futures.order.other.get_closed_position import get_amount_of_closed_position, get_closed_position_side
from function.binance.futures.order.other.get_future_available_balance import get_future_available_balance
from function.binance.futures.order.other.get_future_market_price import get_future_market_price
from function.binance.futures.order.other.get_position_side import get_position_side
from function.binance.futures.order.swap_position_side import swap_position_side
from function.binance.futures.system.create_future_exchange import create_future_exchange
from function.binance.futures.system.retry_utils import run_with_error_handling
from function.message import message


api_key = 'cos73h05s3oxvSK2u7YG2k0mIiu5npSVIXTdyIXXUVNJQOKbRybPNlGOeZNvunVG'
api_secret = 'Zim1iiECBaYdtx3rVlN5mpQ05iQWRXDXU0EBW8LmQW8Ns2X07HhKfIs4Kj3PLzgO'

global_entry_price = None
global_position_entry_time = None
global_position_side = None
global_entry_candle_cross = None

last_entry_candle_cross = None
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

SYMBOL = 'ETHUSDT'
TIMEFRAME = '1m'

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
        try:
            with open(TRADE_RECORD_FILE, 'r') as f:
                trades = json.load(f)
        except FileNotFoundError:
            trades = []

        # Get current market price for conversion and missing prices
        current_price = await get_future_market_price(api_key, api_secret, symbol)
        if current_price is None:
            message(symbol, "Could not get market price for trade recording", "yellow")
            return

        # Use current price if entry_price or exit_price is None
        if entry_price is None:
            entry_price = current_price
            message(symbol, f"Using current price ({current_price}) as entry price", "yellow")
        if exit_price is None:
            exit_price = current_price
            message(symbol, f"Using current price ({current_price}) as exit price", "yellow")

        # Convert amount to float based on different formats
        if isinstance(amount, str):
            amount_str = amount.upper().strip()
            available_balance = await get_future_available_balance(api_key, api_secret)
            available_balance = float(available_balance)
            
            if amount_str == "MAX" or amount_str.endswith('100%'):
                amount = available_balance / current_price
            elif amount_str.endswith('%'):
                percentage = float(amount_str.strip('%'))
                amount = (percentage / 100) * available_balance / current_price
            elif amount_str.endswith('$'):
                amount = float(amount_str.strip('$')) / current_price
            else:
                amount = float(amount)
        
        # Ensure all values are float type
        entry_price = float(entry_price)
        exit_price = float(exit_price)
        amount = float(amount)
        
        # Calculate profit/loss
        try:
            if action in ['BUY', 'SELL']:
                profit_loss = (exit_price - entry_price) * amount if action == 'BUY' else (entry_price - exit_price) * amount
            elif action == 'SWAP':
                profit_loss = (exit_price - entry_price) * amount if exit_price > entry_price else (entry_price - exit_price) * amount
            else:
                profit_loss = 0
                
            profit_loss_percentage = (profit_loss / (entry_price * amount)) * 100 if entry_price and amount else 0
        except Exception as e:
            message(symbol, f"Error calculating profit/loss: {str(e)}", "red")
            profit_loss = 0
            profit_loss_percentage = 0

        # Create trade record
        trade = {
            'timestamp': datetime.now().isoformat(),
            'symbol': symbol,
            'action': action,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'amount': amount,
            'profit_loss': profit_loss,
            'profit_loss_percentage': profit_loss_percentage,
            'reason': reason
        }

        trades.append(trade)

        with open(TRADE_RECORD_FILE, 'w') as f:
            json.dump(trades, f, indent=2)

        message(symbol, f"Trade recorded: {action} {symbol} at price {exit_price:.2f} | Amount: {amount:.8f} | P/L: {profit_loss:.2f} ({profit_loss_percentage:.2f}%)", "cyan")
        
    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"พบปัญหาในการบันทึกการเทรด : {str(e)}", "red")
        message(symbol, "________________________________", "red")
        print(f"Error: {error_traceback}")
        message(symbol, "________________________________", "red")    

# Helper function to get current position details
async def get_position_details(exchange, symbol):
    try:
        positions = await exchange.fetch_positions([symbol])
        return positions[0] if positions else None
    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"Error getting position details: {str(e)}", "red")
        message(SYMBOL, "________________________________", "red")
        print(f"Error: {error_traceback}")
        message(SYMBOL, "________________________________", "red")
        return None

# Helper function to calculate total fees from orders
async def calculate_fees(orders):
    total_fees = 0
    for order in orders:
        if 'fee' in order and order['fee']:
            total_fees += float(order['fee'].get('cost', 0))
    return total_fees

# ฟังก์ชันหลักสำหรับตรวจสอบแท่งเทียนใหม่และ RSI
async def check_new_candle_and_rsi(api_key, api_secret, symbol, timeframe):
    global global_entry_price, global_position_entry_time, global_position_side
    # โหลดสถานะเดิม (ถ้ามี)
    saved_state = load_state()
    last_candle_time = saved_state.get('last_candle_time')
    if last_candle_time:
        last_candle_time = datetime.fromisoformat(last_candle_time)
    if saved_state:
        message(symbol, "System Startup - Loading saved state", "cyan")
        
        # Load global variables
        global_entry_price = saved_state.get('global_entry_price')
        message(symbol, f"global_entry_price: {global_entry_price}", "blue")
        
        global_position_entry_time = saved_state.get('global_position_entry_time')
        if global_position_entry_time:
            global_position_entry_time = datetime.fromisoformat(global_position_entry_time)
        message(symbol, f"global_position_entry_time: {global_position_entry_time}", "blue")
        
        global_position_side = saved_state.get('global_position_side')
        message(symbol, f"global_position_side: {global_position_side}", "blue")

        global_entry_candle_cross = saved_state.get('global_entry_candle_cross')
        message(symbol, f"global_entry_candle_cross: {global_entry_candle_cross}", "blue")
        
        last_entry_candle_cross = saved_state.get('last_entry_candle_cross')
        message(symbol, f"last_entry_candle_cross: {last_entry_candle_cross}", "blue")

        # Load other variables
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
        global_entry_price = None
        global_position_entry_time = None
        global_position_side = None
        global_entry_candle_cross = None

        last_entry_candle_cross = None
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

    while True:
        try:
            
            price = await get_future_market_price(api_key, api_secret, symbol)
            # เมื่อเข้า position ใหม่ (ทั้งปกติและ swap)
            if await check_position(api_key, api_secret, symbol):
                if global_entry_price is None:
                    global_entry_price = price
                    global_position_entry_time = datetime.now(pytz.UTC)
                    global_position_side = await get_position_side(api_key, api_secret, symbol)
                    message(symbol, f"บันทึกราคาเข้า {global_position_side}: {global_entry_price:.2f}", "blue")
            
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
                                else:
                                    if price < last_candle_cross['candle'].get('high', 0) * PRICE_INCREASE and price > (last_candle_cross['candle'].get('low', 0) * PRICE_DECREASE) * 1.02:
                                        await create_order(api_key, api_secret, symbol=symbol, side='sell', price='now', quantity=abs(closed_position_amount), order_type='market')
                                        await create_order(api_key, api_secret, symbol=symbol, side='buy', price=str(last_candle_cross['candle'].get('high', 0) * PRICE_INCREASE), quantity='MAX', order_type='STOPLOSS_MARKET')
                                        isTry_last_entry = False
                                        message(symbol, "เข้า Short ตามสัญญาณ Crossunder สำเร็จ", "green")
                            else:
                                message(symbol, "ไม่สามารถดึงข้อมูลปริมาณ position ที่ปิดได้ ข้ามการสร้างคำสั่งซื้อขาย", "yellow")
                    else:
                        message(symbol, "ไม่มีข้อมูล OHLCV ข้ามรอบนี้", "yellow")
                        isTry_last_entry = False
                else:
                    message(symbol, "ข้อมูล last_candle_cross ไม่ถูกต้อง ข้ามรอบนี้", "yellow")
                    isTry_last_entry = False

            if is_in_position and not is_swapping and not await check_position(api_key, api_secret, symbol):
                #message(symbol, f'is_in_position: {is_in_position} | is_swapping: {is_swapping} | check_position {check_position(api_key, api_secret, symbol)}', "yellow")
                await clear_all_orders(api_key, api_secret, symbol)
                message(symbol, 'position ถูกปิดแล้ว!', "magenta")
                
                # บันทึกการออกจาก position
                exit_price = await get_future_market_price(api_key, api_secret, symbol)
                if global_entry_price is not None:
                    await record_trade(api_key, api_secret, symbol, 
                                    'SELL' if global_position_side == 'buy' else 'BUY',
                                    global_entry_price, exit_price, ENTRY_AMOUNT, 
                                    'Position Closed')
                # รีเซ็ตข้อมูล
                global_entry_price = None
                global_position_entry_time = None
                global_position_side = None
                is_in_position = False
                global_entry_candle_cross = None
                
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
                   
                    is_in_position = True
                    is_wait_candle = False
                else:
                    isTry_last_entry = True
            
            if last_focus_price is not None:
                side = await get_position_side(api_key, api_secret, symbol)
                # ในส่วนของการ swap position (ทั้ง buy และ sell side)
                if side == 'buy':
                    if price < last_focus_price * PRICE_DECREASE:
                        is_swapping = True
                        old_entry_price = global_entry_price
                        old_side = global_position_side
                        
                        await swap_position_side(api_key, api_secret, symbol)
                        await clear_all_orders(api_key, api_secret, symbol)
                        await create_order(api_key, api_secret, symbol=symbol, side='buy',
                                        price=str(last_candle_cross['candle']['high'] * PRICE_INCREASE),
                                        quantity='MAX', order_type='STOPLOSS_MARKET')
                        message(symbol, f"สลับ position จาก {side}", "magenta")
                        
                        # บันทึกการออกจาก position
                        exit_price = await get_future_market_price(api_key, api_secret, symbol)
                        if global_entry_price is not None:
                            await record_trade(api_key, api_secret, symbol, 
                                            'SELL' if global_position_side == 'buy' else 'BUY',
                                            global_entry_price, exit_price, ENTRY_AMOUNT, 
                                            'Position Closed / Swapped to Short!')
                            
                        # อัพเดทข้อมูล position ใหม่
                        global_entry_price = price
                        global_position_entry_time = datetime.now(pytz.UTC)
                        global_position_side = 'sell'
                        global_entry_candle_cross = last_entry_candle_cross

                        # รีเซ็ต entry_candle เพื่อเริ่มนับใหม่
                        entry_candle = await get_current_candle(api_key, api_secret, symbol, timeframe)
                        message(symbol, "รีเซ็ตการนับแท่งเทียนใหม่หลัง swap", "blue")

                        is_swapping = False
                        last_focus_price = None
                        entry_stoploss_price = None

                elif side == 'sell':
                    if price > last_focus_price * PRICE_INCREASE:
                        is_swapping = True
                        old_entry_price = global_entry_price
                        old_side = global_position_side
                        
                        await swap_position_side(api_key, api_secret, symbol)
                        await clear_all_orders(api_key, api_secret, symbol)
                        await create_order(api_key, api_secret, symbol=symbol, side='sell',
                                        price=str(last_candle_cross['candle']['low'] * PRICE_DECREASE),
                                        quantity='MAX', order_type='STOPLOSS_MARKET')
                        message(symbol, f"สลับ position จาก {side}", "magenta")
                        
                        # บันทึกการออกจาก position
                        exit_price = await get_future_market_price(api_key, api_secret, symbol)
                        if global_entry_price is not None:
                            await record_trade(api_key, api_secret, symbol, 
                                            'SELL' if global_position_side == 'buy' else 'BUY',
                                            global_entry_price, exit_price, ENTRY_AMOUNT, 
                                            'Position Closed / Swapped to Long!')
                            
                        # อัพเดทข้อมูล position ใหม่
                        global_entry_price = price
                        global_position_entry_time = datetime.now(pytz.UTC)
                        global_position_side = 'buy'
                        global_entry_candle_cross = last_entry_candle_cross

                        # รีเซ็ต entry_candle เพื่อเริ่มนับใหม่
                        entry_candle = await get_current_candle(api_key, api_secret, symbol, timeframe)
                        message(symbol, "รีเซ็ตการนับแท่งเทียนใหม่หลัง swap", "blue")
                        
                        is_swapping = False
                        last_focus_price = None
                        entry_stoploss_price = None
            
            if entry_price is not None:
                if entry_side == 'buy':
                    if price > entry_price * PRICE_INCREASE:
                        await create_order(api_key, api_secret, symbol=symbol, side=entry_side, price='now', quantity=ENTRY_AMOUNT, order_type='market')
                        await create_order(api_key, api_secret, symbol=symbol, side='sell', price=str(entry_stoploss_price * PRICE_DECREASE), quantity='MAX', order_type='STOPLOSS_MARKET')
                        message(symbol, 'เข้า Long position สำเร็จ', "green")
                        global_entry_candle_cross = last_entry_candle_cross
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
                        global_entry_candle_cross = last_entry_candle_cross
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

                    if is_in_position and global_entry_candle_cross:
                        current_candle = await get_current_candle(api_key, api_secret, symbol, timeframe)
                        if current_candle:
                            # แปลงเวลาของ cross ให้เป็น timestamp
                            cross_time = datetime.strptime(global_entry_candle_cross['candle']['time'], '%d/%m/%Y %H:%M')
                            cross_timestamp = int(cross_time.timestamp() * 1000)  # แปลงเป็น milliseconds
                            
                            # คำนวณจำนวนแท่งที่ผ่านไปตั้งแต่จุด cross
                            time_since_cross = current_candle['timestamp'] - cross_timestamp
                            candles_since_cross = (time_since_cross // get_timeframe_milliseconds(timeframe))
                            
                            # ต้องมีอย่างน้อย 5 แท่ง:
                            # 1 แท่ง cross + 3 แท่งที่ปิดแล้ว + 
                            if candles_since_cross >= 5:
                                position_side = await get_position_side(api_key, api_secret, symbol)
                                if position_side:
                                    current_stoploss = await get_current_stoploss(api_key, api_secret, symbol)
                                    new_stoploss = await adjust_stoploss(api_key, api_secret, symbol, timeframe, position_side, entry_candle['timestamp'], current_stoploss)
                                    if new_stoploss:
                                        message(symbol, f"ปรับ Stoploss เป็น {new_stoploss:.8f} (Three Candle Rule)", "cyan")
                                else:
                                    message(symbol, "ไม่สามารถดึงข้อมูลด้านของ position ข้ามการปรับ Stoploss", "yellow")
                            else:
                                message(symbol, f"รอให้ครบ 3 แท่งที่ปิดแล้วก่อนปรับ Stoploss อีก {4 - candles_since_cross} แท่งเทียน", "blue")
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
                            message(symbol, f"ผลการตรวจสอบ RSI Cross: {isRsiCross.get('type')}", "blue")
                        
                        if isRsiCross['status']:
                            if (isRsiCross['type'] == 'crossunder') or (isRsiCross['type'] == 'crossover'):
                                last_candle_cross = isRsiCross
                            if is_in_position and side is not None:
                                #message(symbol, f"ทิศทางปัจจุบัน = {side} // ประเภท RSI Cross = {isRsiCross['type']}", "blue")
                                if (side == 'buy' and isRsiCross['type'] == 'crossunder') or (side == 'sell' and isRsiCross['type'] == 'crossover'):
                                    last_candle_cross = isRsiCross
                                    last_focus_price = None
                                    last_focus_stopprice = None
                                    is_wait_candle = True
                                    message(symbol, f'พบสัญญาณตรงกันข้าม! รอปิดแท่งเทียน!', "yellow")
                                else:
                                    if last_focus_price is not None:
                                        try:
                                            await clear_all_orders(api_key, api_secret, symbol)
                                            # สร้างคำสั่ง stop loss ใหม่
                                            await change_stoploss_to_price(api_key, api_secret, symbol, last_focus_price)
                                            message(symbol, f"ปรับ Stop Loss เป็น {last_focus_price:.8f}", "cyan")
                                            last_focus_price = None
                                        except Exception as e:
                                            message(symbol, f"เกิดข้อผิดพลาดในการเปลี่ยน stop loss: {str(e)}", "red")
                                    else:
                                        message(symbol, "ไม่สามารถปรับ Stop Loss เนื่องจากไม่พบค่า last_focus_price", "yellow")
                                    
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
                'global_entry_price': global_entry_price,
                'global_position_entry_time': global_position_entry_time.isoformat() if global_position_entry_time else None,
                'global_position_side': global_position_side,
                'global_entry_candle_cross': last_candle_cross,
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
    exchange = await create_future_exchange(api_key, api_secret)
    try:
        # แปลง symbol เป็นรูปแบบที่ exchange ใช้ (เช่น 'ETHUSDT' เป็น 'ETH/USDT:USDT')
        exchange_symbol = symbol
        if 'USDT' in symbol and '/USDT:USDT' not in symbol:
            exchange_symbol = symbol.replace("USDT", "/USDT:USDT")
        
        # ดึงรายการ orders ที่เป็น stop_market ทั้งหมด
        orders = await exchange.fetch_open_orders(symbol)
        
        # ดึง position เพื่อหา side ปัจจุบัน
        positions = await exchange.fetch_positions([symbol])
        current_position = None
        
        for position in positions:
            # เช็ค symbol ทั้งรูปแบบปกติและรูปแบบของ exchange
            if (position['symbol'] == symbol or position['symbol'] == exchange_symbol) and float(position['contracts']) != 0:
                current_position = position
                break
                
        if not current_position:
            message(symbol, "ไม่พบ Position ที่เปิดอยู่", "yellow")
            return None
            
        # หา stop order ที่ตรงกับ side ปัจจุบัน
        current_side = current_position['side']  # 'long' หรือ 'short'
        
        for order in orders:
            # ถ้า position เป็น long, stop loss จะเป็น sell
            # ถ้า position เป็น short, stop loss จะเป็น buy
            if (order['type'] == 'stop_market' and 
                ((current_side == 'long' and order['side'] == 'sell') or 
                 (current_side == 'short' and order['side'] == 'buy'))):
                # ตรวจสอบ stopPrice ในที่ต่างๆ
                stop_price = None
                if 'params' in order and 'stopPrice' in order['params']:
                    stop_price = order['params']['stopPrice']
                elif 'info' in order and 'stopPrice' in order['info']:
                    stop_price = order['info']['stopPrice']
                
                if stop_price is not None:
                    #message(symbol, f"พบ Stop Loss ที่ราคา {float(stop_price)}", "blue")
                    return float(stop_price)
        
        message(symbol, "ไม่พบคำสั่ง Stop Loss ที่เปิดอยู่", "yellow")
        return None

    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"เกิดข้อผิดพลาดในการดึงค่า stoploss ปัจจุบัน: {str(e)}", "red")
        message(symbol, "________________________________", "red")
        print(f"Error: {error_traceback}")
        message(symbol, "________________________________", "red")
        return None
    finally:
        await exchange.close()

async def adjust_stoploss(api_key, api_secret, symbol, timeframe, position_side, cross_timestamp, current_stoploss):
    exchange = None
    try:
        exchange = await create_future_exchange(api_key, api_secret)
        
        # ดึงข้อมูล 5 แท่ง: 1 แท่ง cross + 3 แท่งที่จะใช้ + 1 แท่งปัจจุบัน
        ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, limit=5)
        
        if not ohlcv or len(ohlcv) < 5:
            message(symbol, "ข้อมูล OHLCV ไม่เพียงพอ ข้ามการปรับ stoploss", "yellow")
            return None
        
        # ตัดแท่งสุดท้าย (แท่งปัจจุบันที่ยังไม่ปิด) ออก
        closed_candles = ohlcv[:-1]
        
        # พิจารณาเฉพาะแท่งที่ปิดแล้ว
        if position_side == 'buy':
            prices = [candle[3] for candle in closed_candles]  # ราคาต่ำสุด
            prices_str = [f"{price:.2f}" for price in prices]
            message(symbol, f"กำลังพิจารณาแท่งเทียนที่ปิดแล้ว {len(prices)} แท่ง - Low prices: {', '.join(prices_str)}", "blue")
        elif position_side == 'sell':
            prices = [candle[2] for candle in closed_candles]  # ราคาสูงสุด
            prices_str = [f"{price:.2f}" for price in prices]
            message(symbol, f"กำลังพิจารณาแท่งเทียนที่ปิดแล้ว {len(prices)} แท่ง - High prices: {', '.join(prices_str)}", "blue")
        else:
            raise ValueError("ทิศทาง position ไม่ถูกต้อง ต้องเป็น 'buy' หรือ 'sell' เท่านั้น")

        # เตรียมข้อมูลเวลาของแท่งเทียน
        candle_times = []
        for candle in closed_candles:
            candle_time = datetime.fromtimestamp(candle[0] / 1000, tz=pytz.UTC)
            candle_times.append(candle_time.strftime('%H:%M'))
        message(symbol, f"เวลาของแท่งเทียนที่พิจารณา: {', '.join(candle_times)}", "blue")

        # ค้นหาชุด 3 แท่งที่เข้าเงื่อนไข โดยเริ่มจากแท่งเก่าไปใหม่
        valid_sequences = []
        for i in range(len(prices)-2):
            for j in range(i+1, len(prices)-1):
                for k in range(j+1, len(prices)):
                    if position_side == 'buy':
                        if prices[k] > prices[j] > prices[i]:  # เรียงจากน้อยไปมาก
                            valid_sequences.append((i, j, k))
                    else:  # position_side == 'sell'
                        if prices[k] < prices[j] < prices[i]:  # เรียงจากมากไปน้อย
                            valid_sequences.append((i, j, k))

        if not valid_sequences:
            message(symbol, "ไม่พบชุดแท่งเทียนที่เข้าเงื่อนไข", "yellow")
            return None

        # เลือกชุดที่ใกล้ปัจจุบันที่สุด (มี index น้อยที่สุด)
        best_sequence = min(valid_sequences, key=lambda x: x[0])
        new_stoploss = prices[best_sequence[0]]  # เลือกแท่งแรกของชุด

        # ตรวจสอบเงื่อนไขการปรับ stoploss
        if position_side == 'buy':
            if new_stoploss <= current_stoploss:
                message(symbol, f"ไม่ปรับ stoploss เนื่องจากค่าใหม่ ({new_stoploss:.2f}) ไม่สูงกว่าค่าปัจจุบัน ({current_stoploss:.2f})", "yellow")
                return None
        else:  # position_side == 'sell'
            if new_stoploss >= current_stoploss:
                message(symbol, f"ไม่ปรับ stoploss เนื่องจากค่าใหม่ ({new_stoploss:.2f}) ไม่ต่ำกว่าค่าปัจจุบัน ({current_stoploss:.2f})", "yellow")
                return None

        # ปรับ stoploss
        await change_stoploss_to_price(api_key, api_secret, symbol, new_stoploss)
        sequence_prices = [prices[i] for i in best_sequence]
        sequence_str = ', '.join([f"{price:.2f}" for price in sequence_prices])
        message(symbol, f"ปรับ stoploss จาก {current_stoploss:.2f} เป็น {new_stoploss:.2f} (พิจารณาจากแท่งที่ปิดแล้ว: {sequence_str})", "cyan")

        return new_stoploss

    except Exception as e:
        message(symbol, f"เกิดข้อผิดพลาดขณะปรับ stoploss: {str(e)}", "red")
        return None
    finally:
        if exchange:
            await exchange.close()

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
        await check_new_candle_and_rsi(api_key, api_secret, SYMBOL, TIMEFRAME)
        """await create_order(api_key, api_secret, symbol=SYMBOL, side='sell', price='now', quantity=ENTRY_AMOUNT, order_type='market')
        await create_order(api_key, api_secret, symbol=SYMBOL, side='buy', price='5%', quantity='MAX', order_type='STOPLOSS_MARKET')
        await get_current_stoploss(api_key, api_secret, SYMBOL)"""
    except Exception as e:
        error_traceback = traceback.format_exc()
        message(SYMBOL,f"เกิดข้อผิดพลาดใน main: {str(e)}", "yellow")
        message(SYMBOL, "________________________________", "red")
        print(f"Error: {error_traceback}")
        message(SYMBOL, "________________________________", "red")

# Entry point
if __name__ == "__main__":
    try:
        # ใช้ asyncio.run() with error handling
        asyncio.run(run_with_error_handling(main, SYMBOL))
    except KeyboardInterrupt:
        message('', "โปรแกรมถูกปิดโดยผู้ใช้", "yellow")
    except Exception as e:
        message('', f"เกิดข้อผิดพลาดที่ไม่สามารถกู้คืนได้: {str(e)}", "red")
    finally:
        # Cleanup code
        message('', "กำลังทำความสะอาดและปิดโปรแกรม...", "yellow")
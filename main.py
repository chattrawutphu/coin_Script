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
from function.binance.futures.system.update_symbol_data import update_symbol_data


api_key = 'cos73h05s3oxvSK2u7YG2k0mIiu5npSVIXTdyIXXUVNJQOKbRybPNlGOeZNvunVG'
api_secret = 'Zim1iiECBaYdtx3rVlN5mpQ05iQWRXDXU0EBW8LmQW8Ns2X07HhKfIs4Kj3PLzgO'

TRADING_CONFIG = {
    'ETHUSDT': {
        'timeframe': '1m',
        'entry_amount': '25$',
        'rsi_period': 7,
        'rsi_overbought': 68,
        'rsi_oversold': 32
    },
    'SOLUSDT': {
        'timeframe': '1m',
        'entry_amount': '50$',
        'rsi_period': 4,
        'rsi_overbought': 68,
        'rsi_oversold': 32
    }
}

PRICE_CHANGE_THRESHOLD = 0.0001  # 0.1%
PRICE_INCREASE = 1 + PRICE_CHANGE_THRESHOLD  # 1.001
PRICE_DECREASE = 1 - PRICE_CHANGE_THRESHOLD  # 0.999
PRICE_CHANGE_MAXPERCENT = 5
MAX_CANDLES_TO_FETCH = 5
MIN_CANDLES_TO_FETCH = 3

class TradingConfig:
    """คลาสสำหรับจัดการคอนฟิกของแต่ละเหรียญ"""
    def __init__(self, symbol: str):
        config = TRADING_CONFIG.get(symbol, {})
        self.symbol = symbol
        self.timeframe = config.get('timeframe', '5m')  # ค่าเริ่มต้นถ้าไม่ได้กำหนด
        self.entry_amount = config.get('entry_amount', '25$')
        self.rsi_period = config.get('rsi_period', 7)
        self.rsi_overbought = config.get('rsi_overbought', 68)
        self.rsi_oversold = config.get('rsi_oversold', 32)

class SymbolState:
    """คลาสสำหรับจัดการสถานะของแต่ละเหรียญ"""
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.config = TradingConfig(symbol)
        self.state_file = f'json/state/{symbol}.json'
        self.trade_record_file = f'json/trade_records/{symbol}.json'
        
        # ตัวแปรสถานะ
        self.global_entry_price = None
        self.global_position_entry_time = None
        self.global_position_side = None
        self.last_candle_time = None
        self.last_candle_cross = None
        self.last_focus_price = None
        self.last_focus_stopprice = None
        self.is_wait_candle = False
        self.is_in_position = False
        self.is_swapping = False
        self.isTry_last_entry = False
        self.entry_candle = None
        self.entry_price = None
        self.entry_side = None
        self.entry_stoploss_price = None

    def save_state(self):
        """บันทึกสถานะลงไฟล์"""
        current_state = {
            'global_entry_price': self.global_entry_price,
            'global_position_entry_time': self.global_position_entry_time.isoformat() if self.global_position_entry_time else None,
            'global_position_side': self.global_position_side,
            'last_candle_time': self.last_candle_time.isoformat() if self.last_candle_time else None,
            'last_candle_cross': self.last_candle_cross,
            'last_focus_price': self.last_focus_price,
            'last_focus_stopprice': self.last_focus_stopprice,
            'is_wait_candle': self.is_wait_candle,
            'is_in_position': self.is_in_position,
            'is_swapping': self.is_swapping,
            'isTry_last_entry': self.isTry_last_entry,
            'entry_candle': self.entry_candle,
            'entry_price': self.entry_price,
            'entry_side': self.entry_side,
            'entry_stoploss_price': self.entry_stoploss_price
        }

        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        
        with open(self.state_file, 'w') as f:
            json.dump(current_state, f)

    def load_state(self):
        """โหลดสถานะจากไฟล์"""
        if os.path.exists(self.state_file):
            with open(self.state_file, 'r') as f:
                saved_state = json.load(f)
            
            # โหลดค่าตัวแปรทั้งหมด
            self.global_entry_price = saved_state.get('global_entry_price')
            global_position_entry_time = saved_state.get('global_position_entry_time')
            if global_position_entry_time:
                self.global_position_entry_time = datetime.fromisoformat(global_position_entry_time)
            self.global_position_side = saved_state.get('global_position_side')
            # Load other variables
            last_candle_time = saved_state.get('last_candle_time')
            if last_candle_time:
                self.last_candle_time = datetime.fromisoformat(last_candle_time)
            self.last_candle_cross = saved_state.get('last_candle_cross')
            self.last_focus_price = saved_state.get('last_focus_price')
            self.last_focus_stopprice = saved_state.get('last_focus_stopprice')
            self.is_wait_candle = saved_state.get('is_wait_candle', False)
            self.is_in_position = saved_state.get('is_in_position', False)
            self.is_swapping = saved_state.get('is_swapping', False)
            self.isTry_last_entry = saved_state.get('isTry_last_entry', False)
            self.entry_candle = saved_state.get('entry_candle')
            self.entry_price = saved_state.get('entry_price')
            self.entry_side = saved_state.get('entry_side')
            self.entry_stoploss_price = saved_state.get('entry_stoploss_price')
            message(self.symbol, f"System Startup - โหลดสถานะเสร็จสมบูรณ์ (Timeframe: {self.config.timeframe})", "cyan")
            return True
        message(self.symbol, f"ไม่พบไฟล์สถานะ เริ่มต้นด้วยค่าเริ่มต้น (Timeframe: {self.config.timeframe})", "yellow")
        return False

# ฟังก์ชันสำหรับบันทึกผลการเทรด
async def record_trade(api_key, api_secret, symbol, action, entry_price, exit_price, amount, reason, state):
    try:
        try:
            with open(state.trade_record_file, 'r') as f:
                trades = json.load(f)
        except FileNotFoundError:
            trades = []

        # Get current market price for conversion and missing prices
        current_price = await get_future_market_price(api_key, api_secret, symbol)
        if current_price is None:
            message(symbol, "ไม่สามารถดึงราคาตลาดสำหรับบันทึกการเทรดได้", "yellow")
            return

        # Use current price if entry_price or exit_price is None
        if entry_price is None:
            entry_price = current_price
            message(symbol, f"ใช้ราคาปัจจุบัน ({current_price}) เป็นราคาเข้า", "yellow")
        if exit_price is None:
            exit_price = current_price
            message(symbol, f"ใช้ราคาปัจจุบัน ({current_price}) เป็นราคาออก", "yellow")

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
                if action == 'BUY':
                    # ปิด Long position: exit_price - entry_price
                    profit_loss = (exit_price - entry_price) * amount
                else:  # action == 'SELL'
                    # ปิด Short position: entry_price - exit_price
                    profit_loss = (entry_price - exit_price) * amount
            elif action == 'SWAP':
                # สำหรับ SWAP ให้ดูจากทิศทางราคา
                profit_loss = (exit_price - entry_price) * amount
            else:
                profit_loss = 0
                
            # คำนวณเปอร์เซ็นต์กำไร/ขาดทุน
            profit_loss_percentage = (profit_loss / (entry_price * amount)) * 100 if entry_price and amount else 0

        except Exception as e:
            message(symbol, f"เกิดข้อผิดพลาดในการคำนวณกำไร/ขาดทุน: {str(e)}", "red")
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

        os.makedirs(os.path.dirname(state.trade_record_file), exist_ok=True)

        with open(state.trade_record_file, 'w') as f:
            json.dump(trades, f, indent=2)

        message(symbol, f"บันทึกการเทรด: {action} {symbol} ที่ราคา {exit_price:.2f} | จำนวน: {amount:.8f} | กำไร/ขาดทุน: {profit_loss:.2f} ({profit_loss_percentage:.2f}%)", "cyan")
        
    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"พบปัญหาในการบันทึกการเทรด : {str(e)}", "red")
        message(symbol, "________________________________", "red")
        message(symbol, f"Error: {error_traceback}", "red")
        message(symbol, "________________________________", "red")    

# Helper function to get current position details
async def get_position_details(exchange, symbol):
    try:
        positions = await exchange.fetch_positions([symbol])
        return positions[0] if positions else None
    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"เกิดข้อผิดพลาดในการดึงข้อมูล position: {str(e)}", "red")
        message(symbol, "________________________________", "red")
        message(symbol, f"Error: {error_traceback}", "red")
        message(symbol, "________________________________", "red")
        return None

# Helper function to calculate total fees from orders
async def calculate_fees(orders):
    total_fees = 0
    for order in orders:
        if 'fee' in order and order['fee']:
            total_fees += float(order['fee'].get('cost', 0))
    return total_fees

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
        message(symbol, f"Error: {error_traceback}", "red")
        message(symbol, "________________________________", "red")
        return None
    finally:
        await exchange.close()

async def adjust_stoploss(api_key, api_secret, symbol, state, position_side, cross_timestamp, current_stoploss=None):
    # ใช้ state.config.timeframe แทน timeframe parameter
    timeframe = state.config.timeframe
    exchange = None
    try:
        exchange = await create_future_exchange(api_key, api_secret)
        
        # ดึงข้อมูล 5 แท่ง: 1 แท่ง cross + 3 แท่งที่จะใช้ + 1 แท่งปัจจุบัน
        ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, limit=6)
        
        if not ohlcv or len(ohlcv) < 6:
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

        # ค้นหาชุด 3 แท่งที่เข้าเงื่อนไข โดยเริ่มจากแท่งใหม่ไปเก่า
        valid_sequences = []
        for i in range(len(prices)-1, 1, -1):  # เริ่มจากแท่งสุดท้าย
            for j in range(i-1, 0, -1):  # ถอยมาแท่งก่อนหน้า
                for k in range(j-1, -1, -1):  # ถอยมาแท่งแรกสุด
                    if position_side == 'buy':
                        if prices[i] > prices[j] > prices[k]:  # เรียงจากน้อยไปมาก
                            valid_sequences.append((k, j, i))  # เก็บลำดับ k->j->i
                    else:  # position_side == 'sell'
                        if prices[i] < prices[j] < prices[k]:  # เรียงจากมากไปน้อย
                            valid_sequences.append((k, j, i))  # เก็บลำดับ k->j->i

        if not valid_sequences:
            message(symbol, "ไม่พบชุดแท่งเทียนที่เข้าเงื่อนไข", "yellow")
            return None

        # เลือกชุดแรกที่พบ (จะเป็นชุดที่ใกล้ปัจจุบันที่สุด เพราะเราวนลูปจากท้ายมา)
        best_sequence = valid_sequences[0]  # ไม่ต้องใช้ min() แล้ว
        new_stoploss = prices[best_sequence[0]]  # เลือกแท่งแรกของชุด
        new_stoploss = new_stoploss * PRICE_DECREASE if position_side == 'buy' else new_stoploss * PRICE_INCREASE
        # ตรวจสอบเงื่อนไขการปรับ stoploss
        if current_stoploss is not None:  # เช็คเฉพาะเมื่อมี current_stoploss
            if position_side == 'buy':
                if new_stoploss <= current_stoploss:
                    message(symbol, f"ไม่ปรับ stoploss เนื่องจากค่าใหม่ ({new_stoploss:.2f}) ไม่สูงกว่าค่าปัจจุบัน ({current_stoploss:.2f})", "yellow")
                    return None
            else:  # position_side == 'sell'
                if new_stoploss >= current_stoploss:
                    message(symbol, f"ไม่ปรับ stoploss เนื่องจากค่าใหม่ ({new_stoploss:.2f}) ไม่ต่ำกว่าค่าปัจจุบัน ({current_stoploss:.2f})", "yellow")
                    return None

        # ปรับหรือสร้าง stoploss
        await change_stoploss_to_price(api_key, api_secret, symbol, new_stoploss)
        sequence_prices = [prices[i] for i in best_sequence]
        sequence_str = ', '.join([f"{price:.2f}" for price in sequence_prices])

        if current_stoploss is None:
            message(symbol, f"สร้าง stoploss ที่ราคา {new_stoploss:.2f} เนื่องจากไม่มี stoploss (พิจารณาจากแท่งที่ปิดแล้ว: {sequence_str})", "cyan")
        else:
            message(symbol, f"ปรับ stoploss จาก {current_stoploss:.2f} เป็น {new_stoploss:.2f} (พิจารณาจากแท่งที่ปิดแล้ว: {sequence_str})", "cyan")

        return new_stoploss

    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol,f"เกิดข้อผิดพลาดขณะปรับ stoploss: {str(e)}", "yellow")
        message(symbol, "________________________________", "red")
        message(symbol, f"Error: {error_traceback}", "red")
        message(symbol, "________________________________", "red")
        return None
    finally:
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
        message(symbol, f"Error: {error_traceback}", "red")
        message(symbol, "________________________________", "red")
    return None

async def run_symbol_bot(api_key: str, api_secret: str, symbol: str, state: SymbolState):
    """ฟังก์ชันหลักสำหรับการเทรดของแต่ละเหรียญ รวมฟังก์ชัน check_new_candle_and_rsi เข้าด้วย"""
    try:
        message(symbol, f"เริ่มต้นบอทสำหรับ {symbol} (Timeframe: {state.config.timeframe})", "cyan")
        
        # โหลดสถานะที่บันทึกไว้
        state.load_state()
        exchange = await create_future_exchange(api_key, api_secret)
        state.is_in_position = await check_position(api_key, api_secret, symbol)
        
        while True:
            try:
                price = await get_future_market_price(api_key, api_secret, symbol)
                
                # เมื่อเข้า position ใหม่ (ทั้งปกติและ swap)
                if await check_position(api_key, api_secret, symbol):
                    if state.global_entry_price is None:
                        state.global_entry_price = price
                        state.global_position_entry_time = datetime.now(pytz.UTC)
                        state.global_position_side = await get_position_side(api_key, api_secret, symbol)
                
                if price is None:
                    message(symbol, "ไม่สามารถดึงราคาตลาดได้ ข้ามรอบนี้", "yellow")
                    await asyncio.sleep(1)
                    continue

                # ตรวจสอบและปรับ stoploss เมื่อราคาเคลื่อนที่ตามที่คาดหวัง
                if state.is_wait_candle:
                    side = await get_position_side(api_key, api_secret, symbol)
                    if side == 'buy':
                        if price > state.last_candle_cross['candle']['high'] * PRICE_INCREASE:
                            new_stoploss = state.last_candle_cross['candle']['low'] * PRICE_DECREASE
                            await change_stoploss_to_price(api_key, api_secret, symbol, new_stoploss)
                            message(symbol, f"ปรับ Stop Loss เป็น {new_stoploss:.8f}", "cyan")
                            state.is_wait_candle = False
                    elif side == 'sell':
                        if price < state.last_candle_cross['candle']['low'] * PRICE_DECREASE:
                            new_stoploss = state.last_candle_cross['candle']['high'] * PRICE_INCREASE
                            await change_stoploss_to_price(api_key, api_secret, symbol, new_stoploss)
                            message(symbol, f"ปรับ Stop Loss เป็น {new_stoploss:.8f}", "cyan")
                            state.is_wait_candle = False

                # ตรวจสอบการเข้าซื้อใหม่หลังจาก stop loss
                if state.isTry_last_entry:
                    current_time = datetime.now(pytz.UTC)
                    if state.last_candle_cross and 'candle' in state.last_candle_cross and 'time' in state.last_candle_cross['candle']:
                        last_cross_time = datetime.strptime(state.last_candle_cross['candle']['time'], '%d/%m/%Y %H:%M').replace(tzinfo=pytz.UTC)
                        time_difference = current_time - last_cross_time
                        candles_passed = time_difference.total_seconds() / (timeframe_to_seconds(state.config.timeframe))

                        ohlcv = await exchange.fetch_ohlcv(symbol, state.config.timeframe, since=int(last_cross_time.timestamp() * 1000))
                        
                        if ohlcv:
                            if state.last_candle_cross['type'] == 'crossunder':
                                lowest_price = min(candle[3] for candle in ohlcv)  # Find lowest low
                                reference_price = state.last_candle_cross['candle'].get('low')
                                if reference_price is not None:
                                    price_change_percent = (lowest_price - reference_price) / reference_price * 100
                                else:
                                    message(symbol, "ไม่พบราคาอ้างอิง (ต่ำสุด) ข้ามการคำนวณการเปลี่ยนแปลงราคา", "yellow")
                                    continue
                            else:  # crossover
                                highest_price = max(candle[2] for candle in ohlcv)  # Find highest high
                                reference_price = state.last_candle_cross['candle'].get('high')
                                if reference_price is not None:
                                    price_change_percent = (highest_price - reference_price) / reference_price * 100
                                else:
                                    message(symbol, "ไม่พบราคาอ้างอิง (สูงสุด) ข้ามการคำนวณการเปลี่ยนแปลงราคา", "yellow")
                                    continue

                            if candles_passed <= 5 and abs(price_change_percent) < PRICE_CHANGE_MAXPERCENT:
                                closed_position_amount = await get_amount_of_closed_position(api_key, api_secret, symbol)
                                if closed_position_amount is not None:
                                    if state.last_candle_cross['type'] == 'crossover':
                                        if price > state.last_candle_cross['candle'].get('low', 0) * PRICE_DECREASE and price < (state.last_candle_cross['candle'].get('high', 0) * PRICE_INCREASE) * 1.02:
                                            await create_order(api_key, api_secret, symbol=symbol, side='buy', price='now', quantity=abs(closed_position_amount), order_type='market')
                                            await create_order(api_key, api_secret, symbol=symbol, side='sell', price=str(state.last_candle_cross['candle'].get('low', 0) * PRICE_DECREASE), quantity='MAX', order_type='STOPLOSS_MARKET')
                                            state.isTry_last_entry = False
                                            message(symbol, "เข้า Long ตามสัญญาณ Crossover สำเร็จ", "green")
                                    else:
                                        if price < state.last_candle_cross['candle'].get('high', 0) * PRICE_INCREASE and price > (state.last_candle_cross['candle'].get('low', 0) * PRICE_DECREASE) * 1.02:
                                            await create_order(api_key, api_secret, symbol=symbol, side='sell', price='now', quantity=abs(closed_position_amount), order_type='market')
                                            await create_order(api_key, api_secret, symbol=symbol, side='buy', price=str(state.last_candle_cross['candle'].get('high', 0) * PRICE_INCREASE), quantity='MAX', order_type='STOPLOSS_MARKET')
                                            state.isTry_last_entry = False
                                            message(symbol, "เข้า Short ตามสัญญาณ Crossunder สำเร็จ", "green")
                                else:
                                    message(symbol, "ไม่สามารถดึงข้อมูลปริมาณ position ที่ปิดได้ ข้ามการสร้างคำสั่งซื้อขาย", "yellow")
                        else:
                            message(symbol, "ไม่มีข้อมูล OHLCV ข้ามรอบนี้", "yellow")
                            state.isTry_last_entry = False
                    else:
                        message(symbol, "ข้อมูล last_candle_cross ไม่ถูกต้อง ข้ามรอบนี้", "yellow")
                        state.isTry_last_entry = False

                # ตรวจสอบการปิด position และดำเนินการต่อ
                if state.is_in_position and not state.is_swapping and not await check_position(api_key, api_secret, symbol):
                    await clear_all_orders(api_key, api_secret, symbol)
                    message(symbol, 'position ถูกปิดแล้ว!', "magenta")
                    
                    # บันทึกการออกจาก position
                    exit_price = await get_future_market_price(api_key, api_secret, symbol)
                    if state.global_entry_price is not None:
                        await record_trade(api_key, api_secret, symbol, 
                                        'BUY' if state.global_position_side == 'buy' else 'SELL',
                                        state.global_entry_price, exit_price, state.config.entry_amount, 
                                        'Position Closed', state)
                    # รีเซ็ตข้อมูล
                    state.global_entry_price = None
                    state.global_position_entry_time = None
                    state.global_position_side = None
                    state.is_in_position = False
                    
                    if state.is_wait_candle:
                        closed_position_amount = await get_amount_of_closed_position(api_key, api_secret, symbol)
                        closed_position_side = await get_closed_position_side(api_key, api_secret, symbol)
                        
                        if closed_position_side == 'buy':
                            new_entry_side = 'sell'
                            new_entry_price = price
                            new_stoploss_price = state.last_candle_cross['candle']['high'] * PRICE_INCREASE
                        else:
                            new_entry_side = 'buy'
                            new_entry_price = price
                            new_stoploss_price = state.last_candle_cross['candle']['low'] * PRICE_DECREASE

                        await create_order(api_key, api_secret, symbol=symbol, side=new_entry_side, price='now', quantity=abs(closed_position_amount), order_type='market')
                        await create_order(api_key, api_secret, symbol=symbol, side=('sell' if new_entry_side=='buy' else 'buy'), price=str(new_stoploss_price), quantity='MAX', order_type='STOPLOSS_MARKET')
                        
                        message(symbol, f"เข้า position {new_entry_side} ตรงข้ามสำเร็จ ขนาด: {abs(closed_position_amount):.8f}, Stoploss: {new_stoploss_price:.8f}", "green")
                       
                        state.is_in_position = True
                        state.is_wait_candle = False
                    else:
                        state.isTry_last_entry = True

                # ตรวจสอบเงื่อนไขการ swap position
                if state.last_focus_price is not None:
                    side = await get_position_side(api_key, api_secret, symbol)
                    if side == 'buy':
                        if price < state.last_focus_price * PRICE_DECREASE:
                            state.is_swapping = True
                            old_entry_price = state.global_entry_price
                            old_side = state.global_position_side
                            
                            await swap_position_side(api_key, api_secret, symbol)
                            await clear_all_orders(api_key, api_secret, symbol)
                            await create_order(api_key, api_secret, symbol=symbol, side='buy',
                                            price=str(state.last_candle_cross['candle']['high'] * PRICE_INCREASE),
                                            quantity='MAX', order_type='STOPLOSS_MARKET')
                            message(symbol, f"สลับ position จาก {side}", "magenta")
                            
                            # บันทึกการออกจาก position
                            exit_price = await get_future_market_price(api_key, api_secret, symbol)
                            if state.global_entry_price is not None:
                                await record_trade(api_key, api_secret, symbol, 
                                                'BUY' if state.global_position_side == 'buy' else 'SELL',
                                                state.global_entry_price, exit_price, state.config.entry_amount, 
                                                'Position Closed / Swapped to Short!', state)
                                
                            # อัพเดทข้อมูล position ใหม่
                            state.global_entry_price = price
                            state.global_position_entry_time = datetime.now(pytz.UTC)
                            state.global_position_side = 'sell'

                            # รีเซ็ต entry_candle เพื่อเริ่มนับใหม่
                            state.entry_candle = await get_current_candle(api_key, api_secret, symbol, state.config.timeframe)
                            message(symbol, "รีเซ็ตการนับแท่งเทียนใหม่หลัง swap", "blue")

                            state.is_swapping = False
                            state.last_focus_price = None
                            state.entry_stoploss_price = None

                    elif side == 'sell':
                        if price > state.last_focus_price * PRICE_INCREASE:
                            state.is_swapping = True
                            old_entry_price = state.global_entry_price
                            old_side = state.global_position_side
                            
                            await swap_position_side(api_key, api_secret, symbol)
                            await clear_all_orders(api_key, api_secret, symbol)
                            await create_order(api_key, api_secret, symbol=symbol, side='sell',
                                            price=str(state.last_candle_cross['candle']['low'] * PRICE_DECREASE),
                                            quantity='MAX', order_type='STOPLOSS_MARKET')
                            message(symbol, f"สลับ position จาก {side}", "magenta")
                            
                            # บันทึกการออกจาก position
                            exit_price = await get_future_market_price(api_key, api_secret, symbol)
                            if state.global_entry_price is not None:
                                await record_trade(api_key, api_secret, symbol, 
                                    'BUY' if state.global_position_side == 'buy' else 'SELL',
                                    state.global_entry_price, exit_price, state.config.entry_amount, 
                                    'Position Closed / Swapped to Long!', state)
                            
                            # อัพเดทข้อมูล position ใหม่
                            state.global_entry_price = price
                            state.global_position_entry_time = datetime.now(pytz.UTC)
                            state.global_position_side = 'buy'

                            # รีเซ็ต entry_candle เพื่อเริ่มนับใหม่
                            state.entry_candle = await get_current_candle(api_key, api_secret, symbol, state.config.timeframe)
                            message(symbol, "รีเซ็ตการนับแท่งเทียนใหม่หลัง swap", "blue")
                            
                            state.is_swapping = False
                            state.last_focus_price = None
                            state.entry_stoploss_price = None
                
                # ตรวจสอบการเข้า position ใหม่
                if state.entry_price is not None:
                    if state.entry_side == 'buy':
                        if price > state.entry_price * PRICE_INCREASE:
                            await create_order(api_key, api_secret, symbol=symbol, side=state.entry_side, price='now', quantity=state.config.entry_amount, order_type='market')
                            await create_order(api_key, api_secret, symbol=symbol, side='sell', price=str(state.entry_stoploss_price * PRICE_DECREASE), quantity='MAX', order_type='STOPLOSS_MARKET')
                            message(symbol, 'เข้า Long position สำเร็จ', "green")
                            
                            state.is_in_position = True
                            state.entry_candle = await get_current_candle(api_key, api_secret, symbol, state.config.timeframe)
                            state.entry_price = None
                            state.entry_stoploss_price = None
                            state.entry_side = None
                        elif price < state.entry_stoploss_price * PRICE_DECREASE:
                            message(symbol, 'ยกเลิก Long entry', "yellow")
                            state.entry_price = None
                            state.entry_stoploss_price = None
                            state.entry_side = None
                        else:
                            message(symbol, f'รอราคาทะลุ {state.entry_price:.8f} เพื่อ Long', "blue")
                    elif state.entry_side == 'sell':
                        if price < state.entry_price * PRICE_DECREASE:
                            await create_order(api_key, api_secret, symbol=symbol, side=state.entry_side, price='now', quantity=state.config.entry_amount, order_type='market')
                            await create_order(api_key, api_secret, symbol=symbol, side='buy', price=str(state.entry_stoploss_price * PRICE_INCREASE), quantity='MAX', order_type='STOPLOSS_MARKET')
                            message(symbol, 'เข้า Short position สำเร็จ', "green")
                            
                            state.is_in_position = True
                            state.entry_candle = await get_current_candle(api_key, api_secret, symbol, state.config.timeframe)
                            state.entry_price = None
                            state.entry_stoploss_price = None
                            state.entry_side = None
                        elif price > state.entry_stoploss_price * PRICE_INCREASE:
                            message(symbol, 'ยกเลิก Short entry', "yellow")
                            state.entry_price = None
                            state.entry_stoploss_price = None
                            state.entry_side = None
                        else:
                            message(symbol, f'รอราคาทะลุ {state.entry_price:.8f} เพื่อ Short', "blue")

                # ตรวจสอบแท่งเทียนใหม่และ RSI
                ohlcv = await exchange.fetch_ohlcv(symbol, state.config.timeframe, limit=1)
                
                if ohlcv and len(ohlcv) > 0:
                    current_candle_time = datetime.fromtimestamp(ohlcv[0][0] / 1000, tz=pytz.UTC)
                    
                    # ตรวจสอบแท่งเทียนใหม่
                    if state.last_candle_time is None or current_candle_time > state.last_candle_time:
                        state.last_candle_time = current_candle_time
                        side = await get_position_side(api_key, api_secret, symbol)

                        if state.is_in_position and state.last_candle_cross:
                            current_candle = await get_current_candle(api_key, api_secret, symbol, state.config.timeframe)
                            if current_candle:
                                position_side = await get_position_side(api_key, api_secret, symbol)
                                if position_side:
                                    current_stoploss = await get_current_stoploss(api_key, api_secret, symbol)
                                    new_stoploss = await adjust_stoploss(api_key, api_secret, symbol, state, position_side, state.entry_candle['timestamp'], current_stoploss)
                                else:
                                    message(symbol, "ไม่สามารถดึงข้อมูลด้านของ position ข้ามการปรับ Stoploss", "yellow")
                            else:
                                message(symbol, "ไม่สามารถดึงข้อมูลแท่งเทียนปัจจุบัน ข้ามการปรับ Stoploss", "yellow")
                        
                        if state.is_wait_candle and side is not None:
                            state.is_wait_candle = False
                            if state.last_candle_cross and 'candle' in state.last_candle_cross:
                                state.last_focus_price = min(state.last_candle_cross['candle'].get('low', 0), ohlcv[0][3]) if side == 'buy' else max(state.last_candle_cross['candle'].get('high', 0), ohlcv[0][2])
                                state.last_focus_stopprice = max(state.last_candle_cross['candle'].get('high', 0), ohlcv[0][2]) if side == 'buy' else min(state.last_candle_cross['candle'].get('low', 0), ohlcv[0][3])
                                message(symbol, 'ปิดแท่งเทียนหลังเจอสัญญาณตรงกันข้าม! รอดูว่าจะสลับ position หรือขยับ Stoploss', "yellow")

                        # ตรวจสอบ RSI cross
                        isRsiCross = await get_rsi_cross_last_candle(
                            api_key, api_secret, symbol, 
                            state.config.timeframe,
                            state.config.rsi_period,
                            state.config.rsi_oversold,
                            state.config.rsi_overbought
                        )
                        
                        if isRsiCross and 'status' in isRsiCross:
                            if isRsiCross.get('type') is not None:
                                message(symbol, f"ผลการตรวจสอบ RSI Cross: {isRsiCross.get('type')}", "blue")
                            
                            if isRsiCross['status']:
                                if (isRsiCross['type'] == 'crossunder') or (isRsiCross['type'] == 'crossover'):
                                    state.last_candle_cross = isRsiCross
                                if state.is_in_position and side is not None:
                                    if (side == 'buy' and isRsiCross['type'] == 'crossunder') or (side == 'sell' and isRsiCross['type'] == 'crossover'):
                                        state.last_candle_cross = isRsiCross
                                        state.last_focus_price = None
                                        state.last_focus_stopprice = None
                                        state.is_wait_candle = True
                                        message(symbol, f'พบสัญญาณตรงกันข้าม! รอปิดแท่งเทียน!', "yellow")
                                    else:
                                        if state.last_focus_price is not None:
                                            try:
                                                await clear_all_orders(api_key, api_secret, symbol)
                                                await change_stoploss_to_price(api_key, api_secret, symbol, state.last_focus_price)
                                                message(symbol, f"ปรับ Stop Loss เป็น {state.last_focus_price:.8f}", "cyan")
                                            except Exception as e:
                                                message(symbol, f"เกิดข้อผิดพลาดในการเปลี่ยน stop loss: {str(e)}", "red")
                                            finally:
                                                state.last_focus_price = None
                                        else:
                                            message(symbol, "ไม่สามารถปรับ Stop Loss เนื่องจากไม่พบค่า last_focus_price", "yellow")
                                        
                                elif not state.is_in_position:
                                    await clear_all_orders(api_key, api_secret, symbol)
                                    if 'candle' in isRsiCross:
                                        state.entry_price = isRsiCross['candle'].get('high') if isRsiCross['type'] == 'crossover' else isRsiCross['candle'].get('low')
                                        state.entry_stoploss_price = isRsiCross['candle'].get('low') if isRsiCross['type'] == 'crossover' else isRsiCross['candle'].get('high')
                                        state.entry_side = 'buy' if isRsiCross['type'] == 'crossover' else 'sell'
                                        message(symbol, f"ตั้งค่าการเข้า position : {state.entry_side} ที่ราคา {state.entry_price:.8f}, Stoploss ที่ {state.entry_stoploss_price:.8f}", "blue")
                        else:
                            message(symbol, "ข้อมูล RSI Cross ไม่ถูกต้อง ข้ามรอบนี้", "yellow")
                
                # บันทึกสถานะหลังจบรอบ
                state.save_state()
                await asyncio.sleep(1)
                
            except Exception as e:
                error_traceback = traceback.format_exc()
                message(symbol, f"เกิดข้อผิดพลาด: {str(e)}", "red")
                message(symbol, "________________________________", "red")
                message(symbol, f"Error: {error_traceback}", "red")
                message(symbol, "________________________________", "red")
                await asyncio.sleep(1)
                
    except Exception as e:
        message(symbol, f"เกิดข้อผิดพลาดร้ายแรงใน run_symbol_bot: {str(e)}", "red")
        raise
    finally:
        if exchange:
            await exchange.close()

async def run_bot_wrapper(api_key: str, api_secret: str, symbol: str, state: SymbolState):
    """Wrapper function สำหรับรันบอทแต่ละตัว"""
    while True:
        try:
            await run_symbol_bot(api_key, api_secret, symbol, state)
        except Exception as e:
            message(symbol, f"เกิดข้อผิดพลาดในการรัน bot {symbol}: {str(e)}", "red")
            await asyncio.sleep(5)  # รอก่อนรันใหม่

async def run_with_error_handling(coro, symbol, max_retries=5, retry_delay=60):
    """ฟังก์ชันสำหรับจัดการ error และ retry"""
    retries = 0
    while retries < max_retries:
        try:
            await coro
            break
        except Exception as e:
            retries += 1
            message(symbol, f"เกิดข้อผิดพลาด (ครั้งที่ {retries}/{max_retries}): {str(e)}", "red")
            if retries < max_retries:
                message(symbol, f"รอ {retry_delay} วินาทีก่อนเริ่มใหม่...", "yellow")
                await asyncio.sleep(retry_delay)
            else:
                message(symbol, "เกินจำนวนครั้งที่ลองใหม่ได้ หยุดการทำงาน", "red")
                raise

async def main():
    try:
        tasks = []
        symbol_states = {}

        await update_symbol_data(api_key, api_secret)
        
        for symbol in TRADING_CONFIG.keys():
            state = SymbolState(symbol)
            symbol_states[symbol] = state
            
            # สร้าง coroutine โดยตรง
            coro = run_bot_wrapper(api_key, api_secret, symbol, state)
            # ส่ง coroutine เข้าไปใน run_with_error_handling
            task = asyncio.create_task(run_with_error_handling(coro, symbol))
            tasks.append(task)
            message(symbol, f"สร้าง task สำหรับ {symbol} (Timeframe: {state.config.timeframe})", "cyan")
        
        await asyncio.gather(*tasks)
        
    except Exception as e:
        message("MAIN", f"เกิดข้อผิดพลาดใน main: {str(e)}", "red")
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        message("MAIN", "ปิดโปรแกรมโดยผู้ใช้", "yellow")
    except Exception as e:
        message("MAIN", f"เกิดข้อผิดพลาดร้ายแรง: {str(e)}", "red")
    finally:
        pending = asyncio.all_tasks(loop=loop)
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()
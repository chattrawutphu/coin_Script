import asyncio
from datetime import datetime
import json
import os
import time
import traceback
from functools import wraps
import pytz

from function.binance.futures.check.check_position import check_position
from function.binance.futures.check.check_server_status import check_server_status
from function.binance.futures.check.check_user_api_status import check_user_api_status
from function.binance.futures.get.get_rsi_cross_last_candle import get_rsi_cross_last_candle
from function.binance.futures.order.change_stoploss_to_price import change_stoploss_to_price
from function.binance.futures.order.create_order import create_order, get_adjusted_quantity
from function.binance.futures.order.get_all_order import clear_all_orders
from function.binance.futures.order.other.get_closed_position import get_amount_of_closed_position, get_closed_position_side
from function.binance.futures.order.other.get_future_available_balance import get_future_available_balance
from function.binance.futures.order.other.get_future_market_price import get_future_market_price, get_price_tracker
from function.binance.futures.order.other.get_kline_data import fetch_ohlcv, get_kline_tracker
from function.binance.futures.order.other.get_position_side import get_position_side
from function.binance.futures.order.swap_position_side import swap_position_side
from function.binance.futures.system.create_future_exchange import create_future_exchange
from function.binance.futures.system.retry_utils import run_with_error_handling
from function.message import message
from function.binance.futures.system.update_symbol_data import update_symbol_data
from config import api_key, api_secret

TRADING_CONFIG = {
    'SOLUSDT': {
        'timeframe': '4h',
        'entry_amount': '50$',
        'rsi_period': 7,
        'rsi_overbought': 68,
        'rsi_oversold': 32
    },
        'DOGEUSDT': {
        'timeframe': '4h',
        'entry_amount': '50$',
        'rsi_period': 7,
        'rsi_overbought': 68,
        'rsi_oversold': 32
    },
        'ETHUSDT': {
        'timeframe': '1h',
        'entry_amount': '50$',
        'rsi_period': 7,
        'rsi_overbought': 68,
        'rsi_oversold': 32
    }
}

PRICE_CHANGE_THRESHOLD = 0.0005  # 0.1%
PRICE_INCREASE = 1 + PRICE_CHANGE_THRESHOLD  # 1.001
PRICE_DECREASE = 1 - PRICE_CHANGE_THRESHOLD  # 0.999
PRICE_CHANGE_MAXPERCENT = 0.5
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
        self.entry_candle = None
        self.entry_price = None
        self.entry_side = None
        self.entry_stoploss_price = None
        self.entry_orders = None
        self.tp_levels_hit = {
            'tp1': False,  # สถานะการเลื่อน SL ที่ TP1
            'tp2': False,  # สถานะการปิด 30%
            'tp3': False,  # สถานะการปิด 35%
            'tp4': False   # สถานะการปิดที่เหลือ
        }

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
            'entry_candle': self.entry_candle,
            'entry_price': self.entry_price,
            'entry_side': self.entry_side,
            'entry_stoploss_price': self.entry_stoploss_price,
            'entry_orders': self.entry_orders,
            'tp_levels_hit': self.tp_levels_hit
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
            self.entry_candle = saved_state.get('entry_candle')
            self.entry_price = saved_state.get('entry_price')
            self.entry_side = saved_state.get('entry_side')
            self.entry_stoploss_price = saved_state.get('entry_stoploss_price')
            self.entry_orders = saved_state.get('entry_orders')
            self.tp_levels_hit = saved_state.get('tp_levels_hit', {
                'tp1': False,
                'tp2': False,
                'tp3': False,
                'tp4': False
            })
            message(self.symbol, f"System Startup - โหลดสถานะเสร็จสมบูรณ์ (Timeframe: {self.config.timeframe})", "cyan")
            return True
        message(self.symbol, f"ไม่พบไฟล์สถานะ เริ่มต้นด้วยค่าเริ่มต้น (Timeframe: {self.config.timeframe})", "yellow")
        return False
    
    def reset_position_state(self):
        """รีเซ็ตสถานะทั้งหมดที่เกี่ยวกับ position"""
        #self.is_in_position = False
        #self.global_entry_price = None
        #self.global_position_side = None
        #self.global_position_entry_time = None
        #self.entry_candle = None
        self.tp_levels_hit = {
            'tp1': False,
            'tp2': False,
            'tp3': False,
            'tp4': False
        }

# ฟังก์ชันสำหรับบันทึกผลการเทรด
async def record_trade(api_key, api_secret, symbol, action, entry_price, exit_price, amount, reason, state):
   try:
       # Initialize exchange
       exchange = await create_future_exchange(api_key, api_secret)
       
       try:
           # Load existing trades
           try:
               with open(state.trade_record_file, 'r') as f:
                   trades = json.load(f)
           except FileNotFoundError:
               trades = []

           # Get position and order data from Binance
           positions = await exchange.fetch_positions([symbol])
           position_info = next((p for p in positions if p['symbol'] == symbol), None)
           
           # Get recent orders to find actual entry and exit prices
           orders = await exchange.fetch_orders(symbol, limit=10)
           
           # Find the actual entry and exit orders
           entry_order = None
           exit_order = None
           
           for order in reversed(orders):
               if order['status'] != 'closed':
                   continue
                   
               if not entry_order and (
                   (action == 'BUY' and order['side'].lower() == 'buy') or 
                   (action == 'SELL' and order['side'].lower() == 'sell')
               ):
                   entry_order = order
               elif not exit_order and (
                   (action == 'BUY' and order['side'].lower() == 'sell') or 
                   (action == 'SELL' and order['side'].lower() == 'buy')
               ):
                   exit_order = order

           # แปลงค่าให้เป็น float และจัดการกับ amount
           if position_info and 'info' in position_info:
               actual_entry_price = float(str(position_info['info'].get('entryPrice', 0)).replace(',', ''))
               if actual_entry_price == 0:
                   actual_entry_price = float(str(entry_order['average']).replace(',', '')) if entry_order else float(str(entry_price).replace(',', ''))
               
               actual_amount = abs(float(str(position_info['info'].get('positionAmt', 0)).replace(',', '')))
               if actual_amount == 0:
                   if entry_order:
                       actual_amount = float(str(entry_order['filled']).replace(',', ''))
                   else:
                       # ใช้ get_adjusted_quantity สำหรับแปลง amount
                       adjusted_amount = await get_adjusted_quantity(api_key, api_secret, amount, actual_entry_price, symbol)
                       actual_amount = adjusted_amount if adjusted_amount is not None else 0
               
               actual_exit_price = float(str(exit_order['average']).replace(',', '')) if exit_order else float(str(exit_price).replace(',', ''))
               leverage = float(str(position_info['info'].get('leverage', 20)).replace(',', ''))
               margin_type = position_info['info'].get('marginType', 'cross')
               break_even_price = float(str(position_info['info'].get('breakEvenPrice', 0)).replace(',', ''))
               unrealized_profit = float(str(position_info['info'].get('unRealizedProfit', 0)).replace(',', ''))
           else:
               actual_entry_price = float(str(entry_order['average']).replace(',', '')) if entry_order else float(str(entry_price).replace(',', ''))
               if entry_order:
                   actual_amount = float(str(entry_order['filled']).replace(',', ''))
               else:
                   # ใช้ get_adjusted_quantity สำหรับแปลง amount
                   adjusted_amount = await get_adjusted_quantity(api_key, api_secret, amount, actual_entry_price, symbol)
                   actual_amount = adjusted_amount if adjusted_amount is not None else 0
               
               actual_exit_price = float(str(exit_order['average']).replace(',', '')) if exit_order else float(str(exit_price).replace(',', ''))
               leverage = 20.0
               margin_type = 'cross'
               break_even_price = 0.0
               unrealized_profit = 0.0

           # คำนวณ profit/loss
           if action in ['BUY', 'SELL']:
               if action == 'BUY':
                   profit_loss = (actual_exit_price - actual_entry_price) * actual_amount
               else:  # action == 'SELL'
                   profit_loss = (actual_entry_price - actual_exit_price) * actual_amount
           else:  # action == 'SWAP'
               profit_loss = (actual_exit_price - actual_entry_price) * actual_amount

           # คำนวณ percentage profit/loss
           profit_loss_percentage = (profit_loss / (actual_entry_price * actual_amount)) * 100 if actual_entry_price and actual_amount else 0

           # คำนวณ fees
           total_fees = 0.0
           if entry_order and entry_order.get('fee') and isinstance(entry_order['fee'], dict):
               total_fees += float(str(entry_order['fee'].get('cost', '0')).replace(',', ''))
           if exit_order and exit_order.get('fee') and isinstance(exit_order['fee'], dict):
               total_fees += float(str(exit_order['fee'].get('cost', '0')).replace(',', ''))

           # สร้าง trade record
           trade = {
               'timestamp': datetime.now().isoformat(),
               'symbol': symbol,
               'action': action,
               'entry_price': actual_entry_price,
               'exit_price': actual_exit_price,
               'amount': actual_amount,
               'profit_loss': float(profit_loss),  # แปลงเป็น float ชัดเจน
               'profit_loss_percentage': float(profit_loss_percentage),  # แปลงเป็น float ชัดเจน
               'fees': float(total_fees),  # แปลงเป็น float ชัดเจน
               'reason': reason,
               'leverage': leverage,
               'margin_type': margin_type,
               'break_even_price': break_even_price,
               'unrealized_profit': unrealized_profit,
               'position_size_usd': float(actual_amount * actual_entry_price),  # แปลงเป็น float ชัดเจน
               'entry_order_id': entry_order.get('id') if entry_order else None,
               'exit_order_id': exit_order.get('id') if exit_order else None,
               'entry_time': entry_order.get('datetime') if entry_order else None,
               'exit_time': exit_order.get('datetime') if exit_order else None
           }

           # บันทึก trade
           os.makedirs(os.path.dirname(state.trade_record_file), exist_ok=True)
           trades.append(trade)
           with open(state.trade_record_file, 'w') as f:
               json.dump(trades, f, indent=2)

           # แสดงผลลัพธ์
           message(symbol, f"บันทึกการเทรด: {action} {symbol}", "cyan")
           message(symbol, f"Entry: {actual_entry_price:.2f} | Exit: {actual_exit_price:.2f}", "cyan")
           message(symbol, f"จำนวน: {actual_amount:.8f} ({actual_amount * actual_entry_price:.2f} USD)", "cyan")
           message(symbol, f"Leverage: {leverage}x | Margin Type: {margin_type}", "cyan")
           if break_even_price > 0:
               message(symbol, f"Break-even: {break_even_price:.2f}", "cyan")
           message(symbol, f"กำไร/ขาดทุน: {profit_loss:.2f} USDT ({profit_loss_percentage:.2f}%)", "cyan")
           if total_fees > 0:
               message(symbol, f"ค่าธรรมเนียม: {total_fees:.8f} USDT", "cyan")
           
       except Exception as e:
           error_traceback = traceback.format_exc()
           message(symbol, f"เกิดข้อผิดพลาดในการบันทึกการเทรด: {str(e)}", "red")
           message(symbol, "________________________________", "red")
           message(symbol, f"Error: {error_traceback}", "red")
           message(symbol, "________________________________", "red")
           
   finally:
       if exchange:
           await exchange.close()
           
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
    """ฟังก์ชันปรับ stoploss โดยใช้ค่า PRICE_DECREASE และ PRICE_INCREASE"""
    timeframe = state.config.timeframe
    exchange = None
    try:
        exchange = await create_future_exchange(api_key, api_secret)
        
        # ดึงข้อมูล 5 แท่ง: 1 แท่ง cross + 3 แท่งที่จะใช้ + 1 แท่งปัจจุบัน
        ohlcv = await fetch_ohlcv(symbol, timeframe, limit=6)
        
        if not ohlcv or len(ohlcv) < 6:
            message(symbol, "ข้อมูล OHLCV ไม่เพียงพอ ข้ามการปรับ stoploss", "yellow")
            return None
        
        # ตัดแท่งสุดท้าย (แท่งปัจจุบันที่ยังไม่ปิด) ออก
        closed_candles = ohlcv[:-1]
        
        # พิจารณาเฉพาะแท่งที่ปิดแล้ว และปรับด้วย PRICE_DECREASE/INCREASE
        if position_side == 'buy':
            # ใช้ PRICE_DECREASE สำหรับ low prices เพราะเป็น stoploss ของ long position
            prices = [candle[3] * PRICE_DECREASE for candle in closed_candles]  # ราคาต่ำสุด * PRICE_DECREASE
            prices_str = [f"{price:.2f}" for price in prices]
            #message(symbol, f"กำลังพิจารณาแท่งเทียนที่ปิดแล้ว {len(prices)} แท่ง - Low prices (with {PRICE_DECREASE:.4f}): {', '.join(prices_str)}", "blue")
        elif position_side == 'sell':
            # ใช้ PRICE_INCREASE สำหรับ high prices เพราะเป็น stoploss ของ short position
            prices = [candle[2] * PRICE_INCREASE for candle in closed_candles]  # ราคาสูงสุด * PRICE_INCREASE
            prices_str = [f"{price:.2f}" for price in prices]
            #message(symbol, f"กำลังพิจารณาแท่งเทียนที่ปิดแล้ว {len(prices)} แท่ง - High prices (with {PRICE_INCREASE:.4f}): {', '.join(prices_str)}", "blue")
        else:
            raise ValueError("ทิศทาง position ไม่ถูกต้อง ต้องเป็น 'buy' หรือ 'sell' เท่านั้น")

        # เตรียมข้อมูลเวลาของแท่งเทียน
        candle_times = []
        for candle in closed_candles:
            candle_time = datetime.fromtimestamp(candle[0] / 1000, tz=pytz.UTC)
            candle_times.append(candle_time.strftime('%H:%M'))
        #message(symbol, f"เวลาของแท่งเทียนที่พิจารณา: {', '.join(candle_times)}", "blue")

        # ค้นหาชุด 3 แท่งที่เข้าเงื่อนไข โดยเริ่มจากแท่งใหม่ไปเก่า
        valid_sequences = []
        for i in range(len(prices)-1, 1, -1):
            for j in range(i-1, 0, -1):
                for k in range(j-1, -1, -1):
                    if position_side == 'buy':
                        if prices[i] > prices[j] > prices[k]:  # เรียงจากน้อยไปมาก
                            valid_sequences.append((k, j, i))
                    else:  # position_side == 'sell'
                        if prices[i] < prices[j] < prices[k]:  # เรียงจากมากไปน้อย
                            valid_sequences.append((k, j, i))

        if not valid_sequences:
            message(symbol, "ไม่พบชุดแท่งเทียนที่เข้าเงื่อนไข", "yellow")
            return None

        # เลือกชุดแรกที่พบ (จะเป็นชุดที่ใกล้ปัจจุบันที่สุด)
        best_sequence = valid_sequences[0]
        new_stoploss = prices[best_sequence[0]]  # ไม่ต้องคูณ PRICE_DECREASE/INCREASE อีกเพราะทำไปแล้วตอนสร้าง prices

        # ตรวจสอบเงื่อนไขการปรับ stoploss
        if current_stoploss is not None:
                if position_side == 'buy':
                    if new_stoploss <= current_stoploss:
                        #message(symbol, f"ไม่ปรับ stoploss เนื่องจากค่าใหม่ ({new_stoploss:.2f}) ไม่สูงกว่าค่าปัจจุบัน ({current_stoploss:.2f})", "yellow")
                        return None
                else:  # position_side == 'sell'
                    if new_stoploss >= current_stoploss:
                        #message(symbol, f"ไม่ปรับ stoploss เนื่องจากค่าใหม่ ({new_stoploss:.2f}) ไม่ต่ำกว่าค่าปัจจุบัน ({current_stoploss:.2f})", "yellow")
                        return None
                    
                # เพิ่มการเช็คว่าราคาเท่ากันหรือไม่
                if new_stoploss == current_stoploss:
                    message(symbol, f"ไม่ปรับ stoploss เนื่องจากราคาเท่าเดิม ({current_stoploss:.2f})", "yellow")
                    return None

        # ปรับหรือสร้าง stoploss
        await change_stoploss_to_price(api_key, api_secret, symbol, new_stoploss)
        sequence_prices = [prices[i] for i in best_sequence]
        sequence_str = ', '.join([f"{price:.2f}" for price in sequence_prices])

        if current_stoploss is None:
            message(symbol, f"สร้าง stoploss ที่ราคา {new_stoploss:.2f} (พิจารณาจากแท่งเทียน: {sequence_str})", "cyan")
        else:
            message(symbol, f"ปรับ stoploss จาก {current_stoploss:.2f} เป็น {new_stoploss:.2f} (พิจารณาจากแท่งเทียน: {sequence_str})", "cyan")

        return new_stoploss

    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"เกิดข้อผิดพลาดขณะปรับ stoploss: {str(e)}", "yellow")
        message(symbol, "________________________________", "red")
        message(symbol, f"Error: {error_traceback}", "red")
        message(symbol, "________________________________", "red")
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
        ohlcv = await fetch_ohlcv(symbol, timeframe, limit=1)
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
    """ฟังก์ชันหลักสำหรับการเทรดของแต่ละเหรียญที่ทำงานแบบขนาน"""
    exchange = None
    try:
        message(symbol, f"เริ่มต้นบอทสำหรับ {symbol} (Timeframe: {state.config.timeframe})", "cyan")
        
        # โหลดสถานะที่บันทึกไว้
        state.load_state()
        exchange = await create_future_exchange(api_key, api_secret)
        
        # ตรวจสอบสถานะเริ่มต้นแบบขนาน
        tasks = [
            check_position(api_key, api_secret, symbol),
            get_future_market_price(api_key, api_secret, symbol)
        ]
        initial_checks = await asyncio.gather(*tasks, return_exceptions=True)
        state.is_in_position = initial_checks[0] if not isinstance(initial_checks[0], Exception) else False
        
        # เช็คสัญญาณล่าสุดเมื่อเริ่มต้นถ้าไม่มี position
        if not state.is_in_position and not state.entry_orders:
            rsi_cross = await get_rsi_cross_last_candle(
                api_key, api_secret, symbol,
                state.config.timeframe,
                state.config.rsi_period,
                state.config.rsi_oversold,
                state.config.rsi_overbought
            )
        
        while True:
            try:
                # ดึงข้อมูลพื้นฐานแบบขนาน
                tasks = [
                    get_future_market_price(api_key, api_secret, symbol),
                    check_position(api_key, api_secret, symbol)
                ]

                # เพิ่ม task เมื่อจำเป็น
                if state.is_in_position:
                    tasks.append(get_position_side(api_key, api_secret, symbol))
                else:
                    tasks.append(asyncio.sleep(0))  # Dummy task

                tasks.append(get_current_candle(api_key, api_secret, symbol, state.config.timeframe))
                
                base_data = await asyncio.gather(*tasks, return_exceptions=True)
                
                price = base_data[0] if not isinstance(base_data[0], Exception) else None
                current_position = base_data[1] if not isinstance(base_data[1], Exception) else False
                position_side = base_data[2] if not isinstance(base_data[2], Exception) and state.is_in_position else None
                current_candle = base_data[3] if not isinstance(base_data[3], Exception) else None

                if price is None:
                    message(symbol, "ไม่สามารถดึงราคาตลาดได้ ข้ามรอบนี้", "yellow")
                    await asyncio.sleep(1)
                    continue

                # เมื่อเข้า position ใหม่ (ทั้งปกติและ swap)
                if current_position and state.global_entry_price is None:
                    state.global_entry_price = price
                    state.global_position_entry_time = datetime.now(pytz.UTC)
                    state.global_position_side = position_side

                # ตรวจสอบและดำเนินการ position management แบบขนาน
                position_tasks = []
                
                # Task 1: ตรวจสอบและปรับ stoploss
                if state.is_wait_candle and position_side:
                    position_tasks.append(_handle_stoploss_adjustment(
                        api_key, api_secret, symbol, state, position_side, price
                    ))

                # Task 3: ตรวจสอบการปิด position
                if state.is_in_position and not state.is_swapping and not current_position:
                    position_tasks.append(_handle_position_close(
                        api_key, api_secret, symbol, state, price
                    ))

                # Task 4: ตรวจสอบเงื่อนไขการ swap position
                if state.last_focus_price is not None:
                    position_tasks.append(_handle_position_swap(
                        api_key, api_secret, symbol, state, price, position_side
                    ))

                # Task 5: จัดการ entry orders
                if state.entry_orders:
                    position_tasks.append(_handle_entry_orders(
                        api_key, api_secret, symbol, state, price, exchange
                    ))

                # เพิ่ม task สำหรับจัดการกำไร
                if state.is_in_position and not state.is_swapping:
                    position_tasks.append(manage_position_profit(api_key, api_secret, symbol, state))

                # รันทุก task แบบขนาน
                if position_tasks:
                    await asyncio.gather(*position_tasks, return_exceptions=True)

                # ตรวจสอบแท่งเทียนใหม่และ RSI แบบขนาน
                if current_candle:
                    candle_tasks = [
                        exchange.fetch_ohlcv(symbol, state.config.timeframe, limit=1),
                        get_rsi_cross_last_candle(
                            api_key, api_secret, symbol,
                            state.config.timeframe,
                            state.config.rsi_period,
                            state.config.rsi_oversold,
                            state.config.rsi_overbought
                        )
                    ]
                    candle_data = await asyncio.gather(*candle_tasks, return_exceptions=True)

                    ohlcv = candle_data[0] if not isinstance(candle_data[0], Exception) else None
                    rsi_cross = candle_data[1] if not isinstance(candle_data[1], Exception) else None

                    if ohlcv and len(ohlcv) > 0:
                        current_candle_time = datetime.fromtimestamp(ohlcv[0][0] / 1000, tz=pytz.UTC)
                        
                        # ตรวจสอบแท่งเทียนใหม่
                        if state.last_candle_time is None or current_candle_time > state.last_candle_time:
                            await _handle_new_candle(
                                api_key, api_secret, symbol, state, current_candle_time,
                                position_side, ohlcv, rsi_cross
                            )

                # บันทึกสถานะหลังจบรอบ
                state.save_state()
                await asyncio.sleep(1)
                
            except Exception as e:
                error_traceback = traceback.format_exc()
                message(symbol, f"เกิดข้อผิดพลาด: {str(e)}", "red")
                message(symbol, f"Error: {error_traceback}", "red")
                await asyncio.sleep(1)
                
    except Exception as e:
        message(symbol, f"เกิดข้อผิดพลาดร้ายแรงใน run_symbol_bot: {str(e)}", "red")
        raise
    finally:
        if exchange:
            try:
                await exchange.close()
            except:
                pass

async def _handle_stoploss_adjustment(api_key, api_secret, symbol, state, position_side, price):
    """จัดการการปรับ stoploss แบบแยกขนาน"""
    try:
        if position_side == 'buy':
            if price > state.last_candle_cross['candle']['high'] * PRICE_INCREASE:
                new_stoploss = state.last_candle_cross['candle']['low'] * PRICE_DECREASE
                await change_stoploss_to_price(api_key, api_secret, symbol, new_stoploss)
                message(symbol, f"ปรับ Stop Loss เป็น {new_stoploss:.8f}", "cyan")
                state.is_wait_candle = False
        elif position_side == 'sell':
            if price < state.last_candle_cross['candle']['low'] * PRICE_DECREASE:
                new_stoploss = state.last_candle_cross['candle']['high'] * PRICE_INCREASE
                await change_stoploss_to_price(api_key, api_secret, symbol, new_stoploss)
                message(symbol, f"ปรับ Stop Loss เป็น {new_stoploss:.8f}", "cyan")
                state.is_wait_candle = False
    except Exception as e:
        message(symbol, f"Error in stoploss adjustment: {str(e)}", "red")

async def _show_profit_targets(symbol: str, candle_high: float, candle_low: float):
    """แสดงเป้าหมายการทำกำไรเมื่อเริ่ม position ใหม่"""
    candle_length_percent = abs((candle_high - candle_low) / candle_low * 100)
    
    message(symbol, "====== เป้าหมายการทำกำไร ======", "magenta")
    message(symbol, f"Candle Length: {candle_length_percent:.2f}%", "magenta")
    message(symbol, f"TP1 ({candle_length_percent:.2f}%): ย้าย Stoploss ไปจุดเข้า", "magenta")
    message(symbol, f"TP2 ({candle_length_percent * 2:.2f}%): ปิด 30% ของ position", "magenta")
    message(symbol, f"TP3 ({candle_length_percent * 3:.2f}%): ปิด 35% ของ position", "magenta")
    message(symbol, f"TP4 ({candle_length_percent * 4:.2f}%): ปิด 35% ที่เหลือ", "magenta")
    message(symbol, "==============================", "magenta")

async def manage_position_profit(api_key: str, api_secret: str, symbol: str, state: SymbolState):
    """
    จัดการ position ตามระดับกำไรที่สัมพันธ์กับขนาดของแท่งเทียนที่เกิด position
    """
    exchange = None
    try:
        # ตรวจสอบเงื่อนไขเบื้องต้น
        if not state.is_in_position:
            return
        
        if not state.entry_candle:
            message(symbol, "ไม่พบข้อมูล entry candle ข้ามการจัดการกำไร", "yellow")
            return

        # สร้าง exchange instance
        exchange = await create_future_exchange(api_key, api_secret)

        # ดึงข้อมูลที่จำเป็น
        data_tasks = [
            get_future_market_price(api_key, api_secret, symbol),
            get_current_stoploss(api_key, api_secret, symbol),
            calculate_position_size(api_key, api_secret, symbol)
        ]
        data_results = await asyncio.gather(*data_tasks)
        current_price = data_results[0]
        current_stoploss = data_results[1]
        current_position_size = data_results[2]

        # ตรวจสอบข้อมูลที่จำเป็นแต่ละตัว
        if current_price is None:
            message(symbol, "ไม่สามารถดึงราคาปัจจุบันได้", "yellow")
            return
            
        if current_stoploss is None:
            message(symbol, "ไม่สามารถดึงค่า stoploss ปัจจุบันได้", "yellow")
            return
            
        if current_position_size == 0:
            # รีเซ็ตสถานะเมื่อไม่มี position แล้ว
            if state.is_in_position:
                message(symbol, "ตรวจพบว่าไม่มี position แล้ว - รีเซ็ตสถานะ", "yellow")
                state.reset_position_state()
            return

        # คำนวณ candle length percent และกำไรปัจจุบัน
        candle_high = float(state.entry_candle['high'])
        candle_low = float(state.entry_candle['low'])
        candle_length_percent = abs((candle_high - candle_low) / candle_low * 100)
        
        entry_price = state.global_entry_price
        if state.global_position_side == 'buy':
            current_profit_percent = ((current_price - entry_price) / entry_price) * 100
        else:  # sell
            current_profit_percent = ((entry_price - current_price) / entry_price) * 100

        # แสดงข้อมูลสถานะปัจจุบัน
        """message(symbol, "------- Position Profit Management -------", "blue")
        message(symbol, f"Side: {state.global_position_side.upper()}", "blue")
        message(symbol, f"Entry Candle High: {candle_high:.8f}", "blue")
        message(symbol, f"Entry Candle Low: {candle_low:.8f}", "blue")"""
        message(symbol, f"Candle Length: {candle_length_percent:.2f}%", "blue")
        """message(symbol, f"Entry Price: {entry_price:.8f}", "blue")
        message(symbol, f"Current Price: {current_price:.8f}", "blue")"""
        message(symbol, f"Current Profit: {current_profit_percent:.2f}%", "blue")
        """message(symbol, f"Current Stoploss: {current_stoploss:.8f}", "blue")
        message(symbol, f"Position Size: {current_position_size:.8f}", "blue")
        message(symbol, "-------------------------------------", "blue")"""

        # จัดการตามระดับกำไร
        if current_profit_percent >= candle_length_percent * 4 and not state.tp_levels_hit['tp4']:
            message(symbol, f"กำไรถึงระดับ 4 ({candle_length_percent * 4:.2f}%) - ปิด position ที่เหลือ", "green")
            
            try:
                # ปิด position ที่เหลือทั้งหมด
                close_amount = current_position_size
                message(symbol, f"ส่งคำสั่งปิด position ขนาด {close_amount:.8f}", "green")
                
                order = await create_order(
                    api_key, api_secret,
                    symbol=symbol,
                    side='sell' if state.global_position_side == 'buy' else 'buy',
                    price='now',
                    quantity="MAX",
                    order_type='EXIT_MARKET'
                )
                
                if order:
                    state.reset_position_state()
                    #message(symbol, "รีเซ็ตสถานะ position เรียบร้อย", "green")
                else:
                    message(symbol, "ไม่สามารถส่งคำสั่งปิด position ได้", "red")

            except Exception as e:
                message(symbol, f"เกิดข้อผิดพลาดในการปิด position ระดับ 4: {str(e)}", "red")

        elif current_profit_percent >= candle_length_percent * 3 and not state.tp_levels_hit['tp3']:
            message(symbol, f"กำไรถึงระดับ 3 ({candle_length_percent * 3:.2f}%) - ปิด position 35%", "green")
            
            try:
                close_amount = current_position_size * 0.35
                message(symbol, f"ส่งคำสั่งปิด position ขนาด {close_amount:.8f} (35% ของ {current_position_size:.8f})", "green")
                
                order = await create_order(
                    api_key, api_secret,
                    symbol=symbol,
                    side='sell' if state.global_position_side == 'buy' else 'buy',
                    price='now',
                    quantity="35%",
                    order_type='EXIT_MARKET'
                )
                
                if order:
                    state.tp_levels_hit['tp3'] = True
                else:
                    message(symbol, "ไม่สามารถส่งคำสั่งปิด position ได้", "red")

            except Exception as e:
                message(symbol, f"เกิดข้อผิดพลาดในการปิด position ระดับ 3: {str(e)}", "red")

        elif current_profit_percent >= candle_length_percent * 2 and not state.tp_levels_hit['tp2']:
            message(symbol, f"กำไรถึงระดับ 2 ({candle_length_percent * 2:.2f}%) - ปิด position 30%", "green")
            
            try:
                close_amount = current_position_size * 0.30
                message(symbol, f"ส่งคำสั่งปิด position ขนาด {close_amount:.8f} (30% ของ {current_position_size:.8f})", "green")
                
                order = await create_order(
                    api_key, api_secret,
                    symbol=symbol,
                    side='sell' if state.global_position_side == 'buy' else 'buy',
                    price='now',
                    quantity="30%",
                    order_type='EXIT_MARKET'
                )
                
                if order:
                    state.tp_levels_hit['tp2'] = True
                else:
                    message(symbol, "ไม่สามารถส่งคำสั่งปิด position ได้", "red")

            except Exception as e:
                message(symbol, f"เกิดข้อผิดพลาดในการปิด position ระดับ 2: {str(e)}", "red")

        elif current_profit_percent >= candle_length_percent and not state.tp_levels_hit['tp1']:
            message(symbol, f"กำไรถึงระดับ 1 ({candle_length_percent:.2f}%) - ปรับ stoploss", "cyan")
            
            try:
                # เลื่อน stoploss มาที่จุดเข้า
                if state.global_position_side == 'buy':
                    if current_stoploss < entry_price:
                        message(symbol, f"กำลังปรับ stoploss ไปที่จุดเข้า {entry_price:.8f}", "cyan")
                        await change_stoploss_to_price(api_key, api_secret, symbol, entry_price)
                        state.tp_levels_hit['tp1'] = True
                        message(symbol, "ปรับ stoploss เรียบร้อย", "cyan")
                else:  # sell
                    if current_stoploss > entry_price:
                        message(symbol, f"กำลังปรับ stoploss ไปที่จุดเข้า {entry_price:.8f}", "cyan")
                        await change_stoploss_to_price(api_key, api_secret, symbol, entry_price)
                        state.tp_levels_hit['tp1'] = True
                        message(symbol, "ปรับ stoploss เรียบร้อย", "cyan")

            except Exception as e:
                message(symbol, f"เกิดข้อผิดพลาดในการปรับ stoploss: {str(e)}", "red")

    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"เกิดข้อผิดพลาดในการจัดการกำไร: {str(e)}", "red")
        message(symbol, "________________________________", "red")
        message(symbol, f"Error: {error_traceback}", "red")
        message(symbol, "________________________________", "red")
    finally:
        if exchange:
            try:
                await exchange.close()
            except:
                pass

    # บันทึกสถานะหลังจากทำงานเสร็จ
    state.save_state()

async def calculate_position_size(api_key: str, api_secret: str, symbol: str) -> float:
    """
    คำนวณขนาด position ปัจจุบัน
    """
    exchange = None
    try:
        exchange = await create_future_exchange(api_key, api_secret)
        positions = await exchange.fetch_positions([symbol])

        exchange_symbol = symbol
        if 'USDT' in symbol and '/USDT:USDT' not in symbol:
            exchange_symbol = symbol.replace("USDT", "/USDT:USDT")

        for position in positions:
            if position['symbol'] == symbol or position['symbol'] == exchange_symbol:
                return abs(float(position['contracts']))
        return 0
    except Exception as e:
        message(symbol, f"เกิดข้อผิดพลาดในการคำนวณขนาด position: {str(e)}", "red")
        return 0
    finally:
        if exchange:
            try:
                await exchange.close()
            except:
                pass

async def _handle_position_close(api_key, api_secret, symbol, state, price):
    """จัดการการปิด position แบบขนาน และจัดการการเข้า position ใหม่ถ้าอยู่ในเงื่อนไข"""
    try:
        message(symbol, f"Position ถูก Stoploss!", "red")
        tasks = [
            clear_all_orders(api_key, api_secret, symbol),
            record_trade(api_key, api_secret, symbol,
                        'BUY' if state.global_position_side == 'buy' else 'SELL',
                        state.global_entry_price, price, state.config.entry_amount,
                        'Close Position', 
                        state)
        ]
        await asyncio.gather(*tasks)

        if (state.last_focus_price or state.is_wait_candle) and state.last_candle_cross and 'candle' in state.last_candle_cross:
            message(symbol, "กำลังตรวจสอบเงื่อนไขการเข้า position ใหม่...", "yellow")
            cross_candle = state.last_candle_cross['candle']
            
            # กำหนดค่าเริ่มต้นสำหรับการเข้า position ใหม่
            if state.last_candle_cross['type'] == 'crossover':
                entry_trigger_price = float(cross_candle.get('high')) * PRICE_INCREASE
                stoploss_price = float(cross_candle.get('low')) * PRICE_DECREASE
                entry_side = 'buy'
                stoploss_side = 'sell'
            else:  # crossunder
                entry_trigger_price = float(cross_candle.get('low')) * PRICE_DECREASE
                stoploss_price = float(cross_candle.get('high')) * PRICE_INCREASE
                entry_side = 'sell'
                stoploss_side = 'buy'

            # คำนวณเปอร์เซ็นต์ความต่างของราคา
            price_diff_percent = abs((price - entry_trigger_price) / entry_trigger_price * 100)
            
            # ตรวจสอบเงื่อนไขการเข้า position
            should_market_entry = price_diff_percent < 2.0  # ถ้าราคาต่างไม่เกิน 2%
            
            if (entry_side == 'buy' and price <= entry_trigger_price) or \
               (entry_side == 'sell' and price >= entry_trigger_price) or \
               should_market_entry:
                
                try:
                    entry_order = None
                    if should_market_entry:
                        # เข้าด้วย MARKET order ถ้าราคาต่างไม่เกิน 2%
                        message(symbol, f"ราคาต่างจากจุด trigger {price_diff_percent:.2f}% - เข้าด้วย MARKET", "yellow")
                        entry_order = await create_order(
                            api_key, api_secret,
                            symbol=symbol,
                            side=entry_side,
                            price='now',
                            quantity=state.config.entry_amount,
                            order_type='MARKET'
                        )
                    else:
                        # เข้าด้วย STOP_MARKET ถ้าราคายังอยู่ในช่วง
                        message(symbol, f"ราคายังอยู่ในช่วง - ตั้ง STOP_MARKET ที่ {entry_trigger_price:.8f}", "yellow")
                        entry_order = await create_order(
                            api_key, api_secret,
                            symbol=symbol,
                            side=entry_side,
                            price=str(entry_trigger_price),
                            quantity=state.config.entry_amount,
                            order_type='STOP_MARKET'
                        )

                    if entry_order:
                        # สร้าง Stoploss Order
                        stoploss_order = await create_order(
                            api_key, api_secret,
                            symbol=symbol,
                            side=stoploss_side,
                            price=str(stoploss_price),
                            quantity='MAX',
                            order_type='STOPLOSS_MARKET'
                        )

                        if stoploss_order:
                            if should_market_entry:
                                message(symbol, f"เข้า {entry_side.upper()} ใหม่ด้วย MARKET ORDER สำเร็จ", "green")
                            else:
                                message(symbol, f"ตั้งคำสั่ง {entry_side.upper()} STOP_MARKET ใหม่ที่ราคา {entry_trigger_price:.8f}", "blue")
                            message(symbol, f"ตั้งคำสั่ง Stoploss ที่ราคา {stoploss_price:.8f}", "blue")

                            # อัพเดทสถานะ
                            state.entry_side = entry_side
                            state.entry_price = entry_trigger_price
                            state.entry_stoploss_price = stoploss_price
                            state.entry_orders = {
                                'entry_order': entry_order,
                                'stoploss_order': stoploss_order,
                                'is_market_entry': should_market_entry
                            }
                            state.save_state()

                            # ถ้าเป็น market entry ให้อัพเดทสถานะเพิ่มเติม
                            if should_market_entry:
                                state.is_in_position = True
                                state.global_entry_price = float(entry_order['average'])
                                state.global_position_entry_time = datetime.now(pytz.UTC)
                                state.global_position_side = entry_side
                                state.entry_candle = await get_current_candle(api_key, api_secret, symbol, state.config.timeframe)
                                
                                # รีเซ็ตข้อมูล entry orders
                                state.entry_orders = None
                                state.entry_side = None
                                state.entry_price = None
                                state.entry_stoploss_price = None
                                state.save_state()
                        else:
                            message(symbol, "ไม่สามารถสร้าง Stoploss Order ได้ ยกเลิก Entry Order", "red")
                            await clear_all_orders(api_key, api_secret, symbol)
                    else:
                        message(symbol, "ไม่สามารถสร้าง Entry Order ได้", "red")

                except Exception as e:
                    error_traceback = traceback.format_exc()
                    message(symbol, f"เกิดข้อผิดพลาดในการเข้า position ใหม่: {str(e)}", "red")
                    message(symbol, f"Error: {error_traceback}", "red")
        else:
            # รีเซ็ตสถานะ position
            state.global_entry_price = None
            state.global_position_entry_time = None
            state.global_position_side = None
            state.is_in_position = False
            
    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"Error in position close handling: {str(e)}", "red")
        message(symbol, f"Error: {error_traceback}", "red")

async def _handle_new_candle(api_key, api_secret, symbol, state, current_candle_time,
                         position_side, ohlcv, rsi_cross):
    """จัดการแท่งเทียนใหม่แบบขนาน"""
    try:
        state.last_candle_time = current_candle_time
        tasks = []

        # จัดการ stoploss
        if state.is_in_position and state.last_candle_cross:
            tasks.append(_adjust_stoploss_for_new_candle(
                api_key, api_secret, symbol, state, position_side))

        # จัดการ is_wait_candle
        if state.is_wait_candle and position_side is not None:
            state.is_wait_candle = False
            if state.last_candle_cross and 'candle' in state.last_candle_cross:
                state.last_focus_price = (
                    min(state.last_candle_cross['candle'].get('low', 0), ohlcv[0][3])  # แท่งปัจจุบัน low
                    if position_side == 'buy' else
                    max(state.last_candle_cross['candle'].get('high', 0), ohlcv[0][2])  # แท่งปัจจุบัน high
                )
                state.last_focus_stopprice = (
                    max(state.last_candle_cross['candle'].get('high', 0), ohlcv[0][2])
                    if position_side == 'buy' else
                    min(state.last_candle_cross['candle'].get('low', 0), ohlcv[0][3])
                )
                message(symbol, 'ปิดแท่งเทียนหลังเจอสัญญาณตรงกันข้าม! รอดูว่าจะสลับ position หรือขยับ Stoploss', "yellow")

        # จัดการสัญญาณ RSI
        if rsi_cross and 'status' in rsi_cross and rsi_cross['status']:
            tasks.append(_handle_rsi_signals(
                api_key, api_secret, symbol, state, position_side, rsi_cross, ohlcv[0] if ohlcv else None
            ))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    except Exception as e:
        message(symbol, f"Error in new candle handling: {str(e)}", "red")

async def _handle_rsi_signals(api_key, api_secret, symbol, state, position_side, rsi_cross, ohlcv):
    """จัดการสัญญาณ RSI และสร้าง entry orders แบบ STOP_MARKET หรือ MARKET ตามสถานการณ์"""
    try:
        if rsi_cross['type'] in ['crossunder', 'crossover']:
            state.last_candle_cross = rsi_cross

        if state.is_in_position and position_side:
            # ส่วนจัดการ position ที่มีอยู่ (คงเดิม)
            if ((position_side == 'buy' and rsi_cross['type'] == 'crossunder') or 
                (position_side == 'sell' and rsi_cross['type'] == 'crossover')):
                state.last_candle_cross = rsi_cross
                state.last_focus_price = None
                state.last_focus_stopprice = None
                state.is_wait_candle = True
                message(symbol, f'พบสัญญาณตรงกันข้าม! รอปิดแท่งเทียน!', "yellow")
            else:
                if state.last_focus_price is not None:
                    try:
                        adjust_tasks = [
                            clear_all_orders(api_key, api_secret, symbol),
                            change_stoploss_to_price(api_key, api_secret, symbol, state.last_focus_price)
                        ]
                        await asyncio.gather(*adjust_tasks)
                        message(symbol, f"ปรับ Stop Loss เป็น {state.last_focus_price:.8f}", "cyan")
                        state.last_focus_price = None
                    except Exception as e:
                        message(symbol, f"เกิดข้อผิดพลาดในการเปลี่ยน stop loss: {str(e)}", "red")

        elif not state.is_in_position:  # ไม่มี position
            await clear_all_orders(api_key, api_secret, symbol)
            
            if 'candle' in rsi_cross:
                cross_candle = rsi_cross['candle']
                current_price = await get_future_market_price(api_key, api_secret, symbol)
                
                if current_price is None:
                    message(symbol, "ไม่สามารถดึงราคาตลาดได้ ข้ามการสร้าง Entry Order", "yellow")
                    return
                
                # คำนวณราคาสำหรับ entry และ stoploss
                if rsi_cross['type'] == 'crossover':
                    entry_trigger_price = float(cross_candle.get('high')) * PRICE_INCREASE
                    stoploss_price = float(cross_candle.get('low')) * PRICE_DECREASE
                    entry_side = 'buy'
                    stoploss_side = 'sell'
                    # เช็คว่าราคาปัจจุบันสูงกว่าจุด trigger หรือไม่
                    should_market_entry = current_price > entry_trigger_price
                else:  # crossunder
                    entry_trigger_price = float(cross_candle.get('low')) * PRICE_DECREASE
                    stoploss_price = float(cross_candle.get('high')) * PRICE_INCREASE
                    entry_side = 'sell'
                    stoploss_side = 'buy'
                    # เช็คว่าราคาปัจจุบันต่ำกว่าจุด trigger หรือไม่
                    should_market_entry = current_price < entry_trigger_price
                
                try:
                    entry_order = None
                    if should_market_entry:
                        # ถ้าราคาผ่านจุด trigger แล้ว ให้เข้าด้วย MARKET order เลย
                        message(symbol, f"ราคาผ่านจุด trigger แล้ว ({current_price:.8f} vs {entry_trigger_price:.8f})", "yellow")
                        message(symbol, f"เข้า position ด้วย MARKET order", "yellow")
                        entry_order = await create_order(
                            api_key, api_secret,
                            symbol=symbol,
                            side=entry_side,
                            price='now',  # ใช้ market price
                            quantity=state.config.entry_amount,
                            order_type='MARKET'
                        )
                    else:
                        # ถ้ายังไม่ผ่านจุด trigger ให้ใช้ STOP_MARKET ตามปกติ
                        entry_order = await create_order(
                            api_key, api_secret,
                            symbol=symbol,
                            side=entry_side,
                            price=str(entry_trigger_price),
                            quantity=state.config.entry_amount,
                            order_type='STOP_MARKET'
                        )
                    
                    if entry_order:
                        # สร้าง Stoploss Order
                        stoploss_order = await create_order(
                            api_key, api_secret,
                            symbol=symbol,
                            side=stoploss_side,
                            price=str(stoploss_price),
                            quantity='MAX',
                            order_type='STOPLOSS_MARKET'
                        )
                        
                        if stoploss_order:
                            if should_market_entry:
                                message(symbol, f"เข้า {entry_side.upper()} ด้วย MARKET ORDER สำเร็จ", "green")
                            else:
                                message(symbol, f"ตั้งคำสั่ง {entry_side.upper()} STOP_MARKET ที่ราคา {entry_trigger_price:.8f}", "blue")
                            message(symbol, f"ตั้งคำสั่ง Stoploss ที่ราคา {stoploss_price:.8f}", "blue")
                            
                            # อัพเดทสถานะ
                            state.entry_side = entry_side
                            state.entry_price = entry_trigger_price
                            state.entry_stoploss_price = stoploss_price
                            state.entry_orders = {
                                'entry_order': entry_order,
                                'stoploss_order': stoploss_order,
                                'is_market_entry': should_market_entry
                            }
                            state.save_state()

                            # ถ้าเป็น market entry ให้อัพเดทสถานะเพิ่มเติม
                            if should_market_entry:
                                state.is_in_position = True
                                state.global_entry_price = float(entry_order['average'])
                                state.global_position_entry_time = datetime.now(pytz.UTC)
                                state.global_position_side = entry_side
                                state.entry_candle = await get_current_candle(api_key, api_secret, symbol, state.config.timeframe)
                                
                                # รีเซ็ตข้อมูล entry orders
                                state.entry_orders = None
                                state.entry_side = None
                                state.entry_price = None
                                state.entry_stoploss_price = None
                                state.save_state()
                        else:
                            # ถ้าสร้าง stoploss ไม่สำเร็จ ให้ยกเลิก entry order
                            message(symbol, "ไม่สามารถสร้าง Stoploss Order ได้ ยกเลิก Entry Order", "red")
                            await clear_all_orders(api_key, api_secret, symbol)
                    else:
                        message(symbol, "ไม่สามารถสร้าง Entry Order ได้", "red")
                        
                except Exception as e:
                    error_traceback = traceback.format_exc()
                    message(symbol, f"เกิดข้อผิดพลาดในการสร้างคำสั่ง Entry: {str(e)}", "red")
                    message(symbol, f"Error: {error_traceback}", "red")
                    # Reset states on error
                    state.entry_side = None
                    state.entry_price = None
                    state.entry_stoploss_price = None
                    state.entry_orders = None
                    state.save_state()
                    
    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"Error in RSI signal handling: {str(e)}", "red")
        message(symbol, f"Error: {error_traceback}", "red")
              
async def _handle_entry_orders(api_key: str, api_secret: str, symbol: str, state: SymbolState, price: float, exchange):
    """จัดการ entry orders"""
    try:
        if not state.entry_orders:
            return

        # ดึงข้อมูล order
        try:
            entry_order = state.entry_orders['entry_order']
            entry_order_status = await exchange.fetch_order(entry_order['id'], symbol)
        except Exception as e:
            message(symbol, f"ไม่สามารถดึงข้อมูล order: {str(e)}", "yellow")
            return

        # ตรวจสอบว่า entry order ทำงานแล้ว
        if entry_order_status['status'] == 'closed':
            message(symbol, f"Entry order ทำงานที่ราคา {entry_order_status['average']:.8f}", "green")
            
            # อัพเดทสถานะ position
            state.is_in_position = True
            state.global_entry_price = float(entry_order_status['average'])
            state.global_position_entry_time = datetime.now(pytz.UTC)
            state.global_position_side = state.entry_side
            state.entry_candle = await get_current_candle(api_key, api_secret, symbol, state.config.timeframe)
            
            # แสดงเป้าหมายการทำกำไร
            await _show_profit_targets(symbol, float(state.entry_candle['high']), float(state.entry_candle['low']))
            
            # รีเซ็ตข้อมูล entry orders
            state.entry_orders = None
            state.entry_side = None
            state.entry_price = None
            state.entry_stoploss_price = None
            state.save_state()
            return
            
        # ตรวจสอบว่าควรยกเลิก orders หรือไม่
        if price is not None:
            should_cancel = False
            
            if state.entry_side == 'buy' and price < state.entry_stoploss_price:
                should_cancel = True
                reason = "ราคาต่ำกว่า stoploss"
            elif state.entry_side == 'sell' and price > state.entry_stoploss_price:
                should_cancel = True
                reason = "ราคาสูงกว่า stoploss"
                
            if should_cancel:
                await clear_all_orders(api_key, api_secret, symbol)
                message(symbol, f"ยกเลิก Entry Orders เนื่องจาก{reason}", "yellow")
                
                # รีเซ็ตสถานะ
                state.entry_orders = None
                state.entry_side = None
                state.entry_price = None
                state.entry_stoploss_price = None
                state.save_state()

    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"เกิดข้อผิดพลาดในการจัดการ Entry Orders: {str(e)}", "red")
        message(symbol, f"Error Traceback: {error_traceback}", "red")

async def _handle_position_swap(api_key, api_secret, symbol, state, price, position_side):
    try:
        should_swap = False
        new_side = None
        new_stoploss = None

        # เพิ่มเงื่อนไขตรวจสอบ cross
        if not state.last_candle_cross or 'type' not in state.last_candle_cross:
            return

        # ตรวจสอบว่า cross type ตรงข้ามกับ position ปัจจุบัน
        is_opposite_signal = (
            (position_side == 'buy' and state.last_candle_cross['type'] == 'crossunder') or
            (position_side == 'sell' and state.last_candle_cross['type'] == 'crossover')
        )

        if not is_opposite_signal:
            return

        # ตรวจสอบเงื่อนไขการ swap เหมือนเดิม
        if position_side == 'buy':
            if price < state.last_focus_price * PRICE_DECREASE:
                should_swap = True
                new_side = 'sell'
                new_stoploss = state.last_candle_cross['candle']['high'] * PRICE_INCREASE
        elif position_side == 'sell':
            if price > state.last_focus_price * PRICE_INCREASE:
                should_swap = True
                new_side = 'buy'
                new_stoploss = state.last_candle_cross['candle']['low'] * PRICE_DECREASE
        if should_swap:
            message(symbol, f"สลับ position จาก {position_side} เนื่องจาก:", "magenta")
            message(symbol, f"- มีสัญญาณ {state.last_candle_cross['type']}", "magenta")
            message(symbol, f"- ราคาปัจจุบัน: {price}", "magenta")
            message(symbol, f"- ราคาอ้างอิง: {state.last_focus_price}", "magenta")
        if should_swap:
            state.is_swapping = True
            old_entry_price = state.global_entry_price
            old_side = state.global_position_side

            # ดำเนินการ swap และสร้าง orders แบบขนาน
            swap_tasks = [
                swap_position_side(api_key, api_secret, symbol),
                clear_all_orders(api_key, api_secret, symbol)
            ]
            await asyncio.gather(*swap_tasks)

            # สร้าง stoploss order ใหม่
            await create_order(
                api_key, api_secret, symbol=symbol,
                side='buy' if new_side == 'sell' else 'sell',
                price=str(new_stoploss),
                quantity='MAX',
                order_type='STOPLOSS_MARKET'
            )

            message(symbol, f"สลับ position จาก {position_side}", "magenta")

            # บันทึกการออกจาก position และอัพเดทสถานะแบบขนาน
            exit_price = await get_future_market_price(api_key, api_secret, symbol)
            await record_trade(
                api_key, api_secret, symbol,
                'BUY' if state.global_position_side == 'buy' else 'SELL',
                state.global_entry_price, exit_price, state.config.entry_amount,
                f'Position Closed / Swapped to {new_side.capitalize()}!',
                state
            )

            # อัพเดทข้อมูล position ใหม่
            state.global_entry_price = price
            state.global_position_entry_time = datetime.now(pytz.UTC)
            state.global_position_side = new_side

            # รีเซ็ต entry_candle
            state.entry_candle = await get_current_candle(api_key, api_secret, symbol, state.config.timeframe)
            message(symbol, "รีเซ็ตการนับแท่งเทียนใหม่หลัง swap", "blue")

            state.is_swapping = False
            state.last_focus_price = None
            state.entry_stoploss_price = None

    except Exception as e:
        message(symbol, f"Error in position swap handling: {str(e)}", "red")
        state.is_swapping = False

async def _adjust_stoploss_for_new_candle(api_key, api_secret, symbol, state, position_side):
    """ปรับ stoploss สำหรับแท่งเทียนใหม่แบบแยกขนาน"""
    try:
        # ดึงข้อมูลที่จำเป็นแบบขนาน
        data = await asyncio.gather(
            get_current_candle(api_key, api_secret, symbol, state.config.timeframe),
            get_current_stoploss(api_key, api_secret, symbol),
            return_exceptions=True
        )
        current_candle = data[0] if not isinstance(data[0], Exception) else None
        current_stoploss = data[1] if not isinstance(data[1], Exception) else None

        if current_candle and position_side:
            await adjust_stoploss(
                api_key, api_secret, symbol, state,
                position_side, state.entry_candle['timestamp'],
                current_stoploss
            )
        else:
            if not current_candle:
                message(symbol, "ไม่สามารถดึงข้อมูลแท่งเทียนปัจจุบัน ข้ามการปรับ Stoploss", "yellow")
            if not position_side:
                message(symbol, "ไม่สามารถดึงข้อมูลด้านของ position ข้ามการปรับ Stoploss", "yellow")

    except Exception as e:
        message(symbol, f"Error in stoploss adjustment for new candle: {str(e)}", "red")

async def run_bot_wrapper(api_key: str, api_secret: str, symbol: str, state: SymbolState):
    """Wrapper function สำหรับรันบอทแต่ละตัว"""
    while True:
        try:
            # ตรวจสอบ API key และ secret
            if not await check_user_api_status(api_key, api_secret):
                message(symbol, "❌ ไม่สามารถยืนยัน API Key และ Secret ได้", "red")
                await asyncio.sleep(10)
                continue

            # ตรวจสอบการเชื่อมต่อกับเซิร์ฟเวอร์
            if not await check_server_status(api_key, api_secret):
                message(symbol, "❌ ไม่สามารถเชื่อมต่อกับเซิร์ฟเวอร์ Binance ได้", "red")
                await asyncio.sleep(10)
                continue
            
            # รันบอทหากการเชื่อมต่อปกติ
            await run_symbol_bot(api_key, api_secret, symbol, state)
            
        except Exception as e:
            error_traceback = traceback.format_exc()
            message(symbol, f"เกิดข้อผิดพลาดในการรัน bot {symbol}: {str(e)}", "red")
            message(symbol, "________________________________", "red")
            message(symbol, f"Error Traceback: {error_traceback}", "red")
            message(symbol, "________________________________", "red")
            await asyncio.sleep(5)

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
    price_tracker = None
    kline_tracker = None
    tracker_tasks = []
    trading_tasks = []
    
    try:
        # เริ่มต้น price tracker และ kline tracker
        price_tracker = get_price_tracker()
        kline_tracker = get_kline_tracker()
        
        # สมัครและโหลดข้อมูลเริ่มต้นสำหรับทุกเหรียญ
        init_tasks = []
        for symbol, config in TRADING_CONFIG.items():
            clean_symbol = symbol.lower()
            price_tracker.subscribe_symbol(clean_symbol)
            # สร้าง task สำหรับการโหลดข้อมูลเริ่มต้น
            init_tasks.append(kline_tracker.initialize_symbol_data(symbol, config['timeframe']))
        
        # รอให้โหลดข้อมูลเริ่มต้นเสร็จ
        if init_tasks:
            message("MAIN", "กำลังโหลดข้อมูลแท่งเทียนเริ่มต้น...", "yellow")
            await asyncio.gather(*init_tasks)
            message("MAIN", "โหลดข้อมูลแท่งเทียนเริ่มต้นเสร็จสมบูรณ์", "green")
        
        # เริ่ม trackers
        tracker_tasks = [
            asyncio.create_task(price_tracker.start()),
            asyncio.create_task(kline_tracker.start())
        ]
        
        # รอให้ trackers เริ่มต้นเสร็จ
        await asyncio.sleep(2)  # ให้เวลา trackers เชื่อมต่อ
        
        # สร้าง tasks สำหรับการเทรด
        trading_tasks = []
        symbol_states = {}
        await update_symbol_data(api_key, api_secret)
        
        for symbol in TRADING_CONFIG.keys():
            state = SymbolState(symbol)
            symbol_states[symbol] = state
            main_coro = run_bot_wrapper(api_key, api_secret, symbol, state)
            main_task = asyncio.create_task(run_with_error_handling(main_coro, symbol))
            trading_tasks.append(main_task)
        
        # รวม tracker_tasks และ trading_tasks
        all_tasks = tracker_tasks + trading_tasks
        
        # รอให้ทุก task ทำงานเสร็จ
        await asyncio.gather(*all_tasks)
        
    except Exception as e:
        message("MAIN", f"เกิดข้อผิดพลาดใน main: {str(e)}", "red")
    except KeyboardInterrupt:
        message("MAIN", "ได้รับคำสั่งปิดโปรแกรม กำลังปิดระบบ...", "yellow")
    finally:
        message("MAIN", "กำลังปิดระบบ...", "yellow")
        
        # ยกเลิกทุก task ก่อน
        for task in (tracker_tasks + trading_tasks):
            if not task.done():
                task.cancel()
        
        # หยุด trackers
        if price_tracker:
            await price_tracker.stop()
        if kline_tracker:
            await kline_tracker.stop()
        
        # รอให้ tasks ถูกยกเลิกเสร็จสมบูรณ์
        try:
            await asyncio.gather(*(tracker_tasks + trading_tasks), return_exceptions=True)
        except Exception as e:
            message("MAIN", f"เกิดข้อผิดพลาดขณะปิดระบบ: {str(e)}", "red")
        
        message("MAIN", "ปิดระบบเรียบร้อย", "green")

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
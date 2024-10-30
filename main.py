import asyncio
from datetime import datetime, timedelta
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
from function.binance.futures.order.get_all_order import clear_all_orders, clear_stoploss
from function.binance.futures.order.other.get_adjust_precision_quantity import get_adjust_precision_quantity
from function.binance.futures.order.other.get_closed_position import get_amount_of_closed_position, get_closed_position_side
from function.binance.futures.order.other.get_create_order_adjusted_price import get_adjusted_price
from function.binance.futures.order.other.get_future_available_balance import get_future_available_balance
from function.binance.futures.order.other.get_future_market_price import get_future_market_price, get_price_tracker
from function.binance.futures.order.other.get_kline_data import fetch_ohlcv, get_kline_tracker
from function.binance.futures.order.other.get_position_side import get_position_side
from function.binance.futures.order.swap_position_side import swap_position_side
from function.binance.futures.system.create_future_exchange import create_future_exchange
from function.binance.futures.system.retry_utils import run_with_error_handling
from function.message import message
from function.binance.futures.system.update_symbol_data import update_symbol_data
from config import PRICE_CHANGE_MAXPERCENT, PRICE_CHANGE_THRESHOLD, api_key, api_secret
from config import (
    TRADING_CONFIG,
    PRICE_INCREASE,
    PRICE_DECREASE,
)

async def load_trading_config():
    try:
        config_list = []
        
        # ถ้าไม่มีไฟล์ index.json ให้สร้างใหม่จาก TRADING_CONFIG
        if not os.path.exists('json/index.json'):
            os.makedirs('json', exist_ok=True)
            with open('json/index.json', 'w') as f:
                json.dump(TRADING_CONFIG, f, indent=2)
            message("SYSTEM", "สร้างไฟล์ index.json จาก TRADING_CONFIG", "yellow")
            config_list = TRADING_CONFIG
        else:
            # อ่านค่าจาก index.json
            with open('json/index.json', 'r') as f:
                config_list = json.load(f)
            
        # แปลงลิสต์เป็นดิกชันนารีโดยใช้ symbol เป็น key
        trading_config = {}
        for config in config_list:
            symbol = config['symbol']
            trading_config[symbol] = config
            
        return trading_config
            
    except Exception as e:
        error_traceback = traceback.format_exc()
        message("SYSTEM", f"เกิดข้อผิดพลาดในการโหลด Trading Config: {str(e)}", "red")
        message("SYSTEM", f"Error: {error_traceback}", "red")
        trading_config = {config['symbol']: config for config in TRADING_CONFIG}
        message("SYSTEM", "ใช้ค่า default จาก TRADING_CONFIG แทน", "yellow")
        return trading_config

class TradingConfig:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self._load_config()
        
    def _load_config(self):
        try:
            if os.path.exists('json/index.json'):
                with open('json/index.json', 'r') as f:
                    config_list = json.load(f)
                symbol_config = next((config for config in config_list if config['symbol'] == self.symbol), None)
            else:
                symbol_config = None

            # ถ้าไม่พบใน index.json ให้หาจาก TRADING_CONFIG
            if not symbol_config:
                symbol_config = next((config for config in TRADING_CONFIG if config['symbol'] == self.symbol), None)
                
            if symbol_config:
                # ถ้าพบ config ให้ใช้ค่าจาก config นั้น
                default_config = next((config for config in TRADING_CONFIG if config['symbol'] == self.symbol), {})
                self.timeframe = symbol_config.get('timeframe', default_config.get('timeframe', '4h'))
                self.entry_amount = symbol_config.get('entry_amount', default_config.get('entry_amount', '50$'))
                self.rsi_period = symbol_config.get('rsi_period', default_config.get('rsi_period', 7))
                self.rsi_overbought = symbol_config.get('rsi_overbought', default_config.get('rsi_overbought', 68))
                self.rsi_oversold = symbol_config.get('rsi_oversold', default_config.get('rsi_oversold', 32))
                self.min_stoploss = symbol_config.get('min_stoploss', default_config.get('min_stoploss', None))
                self.max_stoploss = symbol_config.get('max_stoploss', default_config.get('max_stoploss', None))
                self.fix_stoploss = symbol_config.get('fix_stoploss', default_config.get('fix_stoploss', 2))
            else:
                # ถ้าไม่พบ config เลย ให้ใช้ค่า default จาก TRADING_CONFIG ตัวแรก
                default_config = TRADING_CONFIG[0]
                message(self.symbol, f"ไม่พบการตั้งค่าสำหรับ {self.symbol} ใช้ค่า default", "yellow")
                self.timeframe = default_config['timeframe']
                self.entry_amount = default_config['entry_amount']
                self.rsi_period = default_config['rsi_period']
                self.rsi_overbought = default_config['rsi_overbought']
                self.rsi_oversold = default_config['rsi_oversold']
                self.min_stoploss = default_config.get('min_stoploss', None)
                self.max_stoploss = default_config.get('max_stoploss', None)
                self.fix_stoploss = default_config.get('fix_stoploss', 2)
                
        except Exception as e:
            error_traceback = traceback.format_exc()
            message(self.symbol, f"เกิดข้อผิดพลาดในการโหลด config: {str(e)}", "red")
            message(self.symbol, f"Error: {error_traceback}", "red")
            # ใช้ค่า default จาก TRADING_CONFIG ตัวแรก
            default_config = TRADING_CONFIG[0]
            self.timeframe = default_config['timeframe']
            self.entry_amount = default_config['entry_amount']
            self.rsi_period = default_config['rsi_period']
            self.rsi_overbought = default_config['rsi_overbought']
            self.rsi_oversold = default_config['rsi_oversold']
            self.min_stoploss = default_config.get('min_stoploss', None)
            self.max_stoploss = default_config.get('max_stoploss', None)
            self.fix_stoploss = default_config.get('fix_stoploss', 2)

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
        # เพิ่มตัวแปรใหม่
        self.stop_price = None  # ราคา stop loss ปัจจุบัน
        self.current_price = None  # ราคาปัจจุบัน
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
            # เพิ่มฟิลด์ใหม่
            'stop_price': self.stop_price,
            'current_price': self.current_price,
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
            # โหลดค่าฟิลด์ใหม่
            self.stop_price = saved_state.get('stop_price')
            self.current_price = saved_state.get('current_price')
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
            get_future_market_price(api_key, api_secret, symbol),
            exchange.fetch_ohlcv(symbol, state.config.timeframe, limit=3)
        ]
        initial_checks = await asyncio.gather(*tasks, return_exceptions=True)
        
        state.is_in_position = initial_checks[0] if not isinstance(initial_checks[0], Exception) else False
        initial_price = initial_checks[1] if not isinstance(initial_checks[1], Exception) else None
        initial_ohlcv = initial_checks[2] if not isinstance(initial_checks[2], Exception) else None

        # ตรวจสอบและอัพเดทแท่งเทียนล่าสุดตอนเริ่มโปรแกรม
        if initial_ohlcv and len(initial_ohlcv) >= 3:
            bangkok_tz = pytz.timezone('Asia/Bangkok')
            current_time = datetime.now(bangkok_tz)
            
            last_closed_candle = initial_ohlcv[-2]
            last_closed_time = datetime.fromtimestamp(last_closed_candle[0] / 1000, tz=pytz.UTC).astimezone(bangkok_tz)
            
            """message(symbol, "กำลังตรวจสอบแท่งเทียนล่าสุด...", "cyan")
            message(symbol, f"System time (BKK): {current_time.strftime('%Y-%m-%d %H:%M:%S %Z')}", "blue")
            
            if state.last_candle_time:
                message(symbol, f"Last saved candle: {state.last_candle_time.astimezone(bangkok_tz).strftime('%Y-%m-%d %H:%M:%S %Z')}", "blue")
            message(symbol, f"Latest closed candle: {last_closed_time.strftime('%Y-%m-%d %H:%M:%S %Z')}", "blue")"""
            if not state.is_in_position and not state.entry_orders:
                # ดึง RSI cross
                rsi_cross = await get_rsi_cross_last_candle(
                    api_key, api_secret, symbol,
                    state.config.timeframe,
                    state.config.rsi_period,
                    state.config.rsi_oversold,
                    state.config.rsi_overbought
                )
                
                if rsi_cross['type'] != None :
                    message(symbol, f"พบสัญญาณ RSI: {rsi_cross['type']}", "cyan")
                
                # ถ้ามี position ให้ดึง position_side
                position_side = None
                if state.is_in_position:
                    position_side = await get_position_side(api_key, api_secret, symbol)
                
                # อัพเดทแท่งล่าสุด
                await _handle_new_candle(
                    api_key, api_secret, symbol, state, last_closed_time,
                    position_side, [last_closed_candle], rsi_cross
                )
                message(symbol, "อัพเดทแท่งเทียนล่าสุดเรียบร้อย", "cyan")
        
        # Main loop
        #message(symbol, "เริ่มการทำงานปกติ...", "green")
        while True:
            try:
                # ดึงข้อมูลพื้นฐานแบบขนาน
                tasks = [
                    get_future_market_price(api_key, api_secret, symbol),
                    check_position(api_key, api_secret, symbol),
                    get_current_stoploss(api_key, api_secret, symbol),
                ]

                if state.is_in_position:
                    tasks.append(get_position_side(api_key, api_secret, symbol))
                else:
                    tasks.append(asyncio.sleep(0))

                tasks.append(get_current_candle(api_key, api_secret, symbol, state.config.timeframe))
                
                base_data = await asyncio.gather(*tasks, return_exceptions=True)
                
                price = base_data[0] if not isinstance(base_data[0], Exception) else None
                current_position = base_data[1] if not isinstance(base_data[1], Exception) else False
                current_stop = base_data[2] if not isinstance(base_data[2], Exception) else None
                position_side = base_data[3] if not isinstance(base_data[3], Exception) and state.is_in_position else None
                current_candle = base_data[4] if not isinstance(base_data[4], Exception) else None

                if price is None:
                    message(symbol, "ไม่สามารถดึงราคาตลาดได้ ข้ามรอบนี้", "yellow")
                    await asyncio.sleep(1)
                    continue

                # อัพเดทค่าในสถานะ
                state.current_price = price
                if state.is_in_position and current_stop is not None:
                    state.stop_price = current_stop
                elif not state.is_in_position:
                    state.stop_price = None

                # ถ้าไม่มี position แล้ว รีเซ็ตค่าที่เกี่ยวข้อง
                if not current_position and state.is_in_position:
                    state.is_in_position = False
                    state.global_entry_price = None
                    state.global_position_side = None
                    state.global_position_entry_time = None
                    state.stop_price = None

                # เมื่อเข้า position ใหม่
                if current_position and state.global_entry_price is None:
                    state.reset_position_state()
                    state.global_entry_price = price
                    state.global_position_entry_time = datetime.now(pytz.UTC)
                    state.global_position_side = position_side

                # Position management tasks
                position_tasks = []
                
                if state.is_wait_candle and position_side:
                    position_tasks.append(_handle_stoploss_adjustment(
                        api_key, api_secret, symbol, state, position_side, price
                    ))

                if state.is_in_position and not state.is_swapping and not current_position:
                    position_tasks.append(_handle_position_close(
                        api_key, api_secret, symbol, state, price
                    ))

                if state.last_focus_price is not None:
                    position_tasks.append(_handle_position_swap(
                        api_key, api_secret, symbol, state, price, position_side
                    ))

                if state.entry_orders:
                    position_tasks.append(_handle_entry_orders(
                        api_key, api_secret, symbol, state, price, exchange
                    ))

                if state.is_in_position and not state.is_swapping:
                    position_tasks.append(manage_position_profit(api_key, api_secret, symbol, state))

                if position_tasks:
                    await asyncio.gather(*position_tasks, return_exceptions=True)

                # Candle check
                if current_candle:
                    try:
                        candle_tasks = [
                            exchange.fetch_ohlcv(symbol, state.config.timeframe, limit=3),
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

                        if ohlcv and len(ohlcv) >= 3:
                            current_candle = ohlcv[-1]
                            last_closed_candle = ohlcv[-2]
                            previous_closed_candle = ohlcv[-3]
                            
                            if len(last_closed_candle) >= 6:
                                bangkok_tz = pytz.timezone('Asia/Bangkok')
                                current_time = datetime.now(bangkok_tz)
                                last_closed_time = datetime.fromtimestamp(last_closed_candle[0] / 1000, tz=pytz.UTC).astimezone(bangkok_tz)
                                current_candle_time = datetime.fromtimestamp(current_candle[0] / 1000, tz=pytz.UTC).astimezone(bangkok_tz)
                                
                                """message(symbol, f"System time (BKK): {current_time.strftime('%Y-%m-%d %H:%M:%S %Z')}", "blue")
                                if state.last_candle_time:
                                    last_candle_bkk = state.last_candle_time.astimezone(bangkok_tz)
                                    message(symbol, f"Previous candle (BKK): {last_candle_bkk.strftime('%Y-%m-%d %H:%M:%S %Z')}", "blue")
                                message(symbol, f"Last closed candle (BKK): {last_closed_time.strftime('%Y-%m-%d %H:%M:%S %Z')}", "blue")
                                message(symbol, f"Current candle (BKK): {current_candle_time.strftime('%Y-%m-%d %H:%M:%S %Z')}", "blue")"""

                                # Time calculations
                                tf_value = int(state.config.timeframe[:-1])
                                tf_unit = state.config.timeframe[-1]
                                minutes_per_candle = tf_value * 60 if tf_unit == 'h' else tf_value

                                total_minutes = current_time.hour * 60 + current_time.minute
                                minutes_since_last_candle = total_minutes % minutes_per_candle
                                minutes_to_next = minutes_per_candle - minutes_since_last_candle

                                next_candle_time = current_time + timedelta(minutes=minutes_to_next)
                                next_candle_time = next_candle_time.replace(second=0, microsecond=0)

                                time_until_next = next_candle_time - current_time
                                minutes_remaining = int(time_until_next.total_seconds() / 60)

                                if (state.last_candle_time is None or 
                                    last_closed_time > state.last_candle_time.astimezone(bangkok_tz)):
                                    
                                    message(symbol, f"Found new {state.config.timeframe} candle", "cyan")
                                    """message(symbol, f"Candle Open: {last_closed_candle[1]}", "cyan")
                                    message(symbol, f"Candle Close: {last_closed_candle[4]}", "cyan")
                                    message(symbol, f"Candle Volume: {last_closed_candle[5]}", "cyan")"""
                                    
                                    await _handle_new_candle(
                                        api_key, api_secret, symbol, state, last_closed_time,
                                        position_side, [last_closed_candle], rsi_cross
                                    )
                                else:
                                    """message(symbol, f"Waiting for next {state.config.timeframe} candle in {minutes_remaining} minutes", "blue")
                                    message(symbol, f"Next candle at (BKK): {next_candle_time.strftime('%Y-%m-%d %H:%M:%S %Z')}", "blue")
                                    message(symbol, f"Minutes per candle: {minutes_per_candle}", "blue")
                                    message(symbol, f"Minutes since last candle: {minutes_since_last_candle}", "blue")"""
                            else:
                                message(symbol, f"Invalid candle data format: {last_closed_candle}", "yellow")
                        else:
                            message(symbol, f"Insufficient OHLCV data. Got {len(ohlcv) if ohlcv else 0} candles", "yellow")
                            
                    except Exception as e:
                        error_traceback = traceback.format_exc()
                        message(symbol, f"Error in candle processing: {str(e)}", "red")
                        message(symbol, f"Error Traceback: {error_traceback}", "red")

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
            #message(symbol, "ไม่พบ Position ที่เปิดอยู่", "yellow")
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

# check stoploss 3 candle
async def adjust_stoploss(api_key, api_secret, symbol, state, position_side, cross_timestamp, current_stoploss=None):
    """ฟังก์ชันปรับ stoploss โดยใช้ค่า PRICE_DECREASE และ PRICE_INCREASE"""
    timeframe = state.config.timeframe
    exchange = None
    try:
        if not state.entry_candle:
            message(symbol, "ไม่พบข้อมูล entry candle ข้ามการปรับ stoploss", "yellow")
            return None
            
        exchange = await create_future_exchange(api_key, api_secret)
        
        # ดึงข้อมูล 5 แท่ง: 1 แท่ง cross + 3 แท่งที่จะใช้ + 1 แท่งปัจจุบัน
        ohlcv = await fetch_ohlcv(symbol, timeframe, limit=6)
        
        if not ohlcv or len(ohlcv) < 6:
            message(symbol, "ข้อมูล OHLCV ไม่เพียงพอ ข้ามการปรับ stoploss", "yellow")
            return None
        
        # ตัดแท่งสุดท้าย (แท่งปัจจุบันที่ยังไม่ปิด) ออก
        closed_candles = ohlcv[:-1]
        
        # กรองเอาเฉพาะแท่งที่มาหลัง entry_candle
        entry_timestamp = state.entry_candle['timestamp']
        filtered_candles = [candle for candle in closed_candles if candle[0] >= entry_timestamp]
        
        if len(filtered_candles) < 3:
            message(symbol, f"มีแท่งเทียนหลัง entry ไม่พอ ({len(filtered_candles)}/3) ข้ามการปรับ stoploss", "yellow")
            return None
        
        # พิจารณาเฉพาะแท่งที่ปิดแล้ว และปรับด้วย PRICE_DECREASE/INCREASE
        if position_side == 'buy':
            prices = [candle[3] * PRICE_DECREASE for candle in filtered_candles]  # ราคาต่ำสุด * PRICE_DECREASE
        elif position_side == 'sell':
            prices = [candle[2] * PRICE_INCREASE for candle in filtered_candles]  # ราคาสูงสุด * PRICE_INCREASE
        else:
            raise ValueError("ทิศทาง position ไม่ถูกต้อง ต้องเป็น 'buy' หรือ 'sell' เท่านั้น")

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
        new_stoploss = prices[best_sequence[0]]

        # ตรวจสอบเงื่อนไขการปรับ stoploss
        if current_stoploss is not None:
            if position_side == 'buy':
                if new_stoploss <= current_stoploss:
                    return None
            else:  # position_side == 'sell'
                if new_stoploss >= current_stoploss:
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
        message(symbol, f"Error: {error_traceback}", "red")
        return None
    finally:
        if exchange:
            await exchange.close()

# min max fix - stoploss
async def adjust_quantity_for_stoploss(api_key: str, api_secret: str, symbol: str, entry_price: float, stoploss_price: float, quantity: float, state: SymbolState) -> float:
    try:
        config = state.config
        current_percent = abs((entry_price - stoploss_price) / entry_price * 100)

        # ถ้ามี fix_stoploss ใช้ค่านี้อย่างเดียว
        if config.fix_stoploss is not None:
            target_percent = float(config.fix_stoploss)
            adjustment_ratio = target_percent / current_percent
            new_quantity = quantity * adjustment_ratio
            message(symbol, f"ปรับ quantity ตาม fix stoploss {target_percent}% " +
                          f"(SL ปัจจุบัน: {current_percent:.2f}%, ratio: {adjustment_ratio:.4f})", "blue")
            return await get_adjust_precision_quantity(symbol, new_quantity)

        # เช็ค min_stoploss
        if config.min_stoploss is not None and current_percent < float(config.min_stoploss):
            target_percent = float(config.min_stoploss)
            adjustment_ratio = target_percent / current_percent
            new_quantity = quantity * adjustment_ratio
            message(symbol, f"เพิ่ม quantity ตาม min stoploss {target_percent}% " +
                          f"(SL ปัจจุบัน: {current_percent:.2f}%, ratio: {adjustment_ratio:.4f})", "blue")
            return await get_adjust_precision_quantity(symbol, new_quantity)

        # เช็ค max_stoploss
        if config.max_stoploss is not None and current_percent > float(config.max_stoploss):
            target_percent = float(config.max_stoploss)
            adjustment_ratio = target_percent / current_percent
            new_quantity = quantity * adjustment_ratio
            message(symbol, f"ลด quantity ตาม max stoploss {target_percent}% " +
                          f"(SL ปัจจุบัน: {current_percent:.2f}%, ratio: {adjustment_ratio:.4f})", "blue")
            return await get_adjust_precision_quantity(symbol, new_quantity)

        return quantity

    except Exception as e:
        message(symbol, f"Error adjusting quantity: {str(e)}", "red")
        return quantity
    
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
    message(symbol, f"TP2 ({candle_length_percent * 2:.2f}%): ปิด 20% ของ position", "magenta")
    message(symbol, f"TP3 ({candle_length_percent * 3:.2f}%): ปิด 25% ของ position", "magenta")
    message(symbol, f"TP4 ({candle_length_percent * 4:.2f}%): ปิด 25% ที่เหลือ", "magenta")
    message(symbol, "==============================", "magenta")

async def calculate_atr(api_key, api_secret, symbol, timeframe, length=7):
    """คำนวณ ATR (Average True Range) โดยใช้ RMA smoothing"""
    try:
        exchange = await create_future_exchange(api_key, api_secret)
        # ดึงข้อมูลเพิ่มเพื่อให้มีพอสำหรับคำนวณ
        ohlcv = await fetch_ohlcv(symbol, timeframe, limit=length + 1)
        
        if len(ohlcv) < length + 1:
            message(symbol, f"ข้อมูลไม่พอสำหรับคำนวณ ATR (ต้องการ {length + 1} แท่ง)", "yellow")
            return None

        # คำนวณ True Range
        tr_values = []
        for i in range(1, len(ohlcv)):
            high = ohlcv[i][2]
            low = ohlcv[i][3]
            prev_close = ohlcv[i-1][4]
            
            tr = max(
                high - low,  # Current high - low
                abs(high - prev_close),  # Current high - previous close
                abs(low - prev_close)  # Current low - previous close
            )
            tr_values.append(tr)

        # คำนวณ RMA (Rolling Moving Average)
        alpha = 1.0 / length
        rma = tr_values[0]  # ค่าเริ่มต้น
        
        for tr in tr_values[1:]:
            rma = (alpha * tr) + ((1 - alpha) * rma)

        return rma

    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"เกิดข้อผิดพลาดในการคำนวณ ATR: {str(e)}", "red")
        message(symbol, f"Error: {error_traceback}", "red")
        return None
    finally:
        if exchange:
            await exchange.close()

async def setup_take_profit_orders(api_key, api_secret, symbol, entry_price, position_side, timeframe):
    """สร้าง take profit orders โดยใช้ ATR เป็นฐานในการคำนวณระยะห่าง"""
    try:
        # ตรวจสอบข้อมูลนำเข้า
        if entry_price is None:
            message(symbol, "ไม่มีข้อมูล entry price สำหรับคำนวณ Take Profit", "red")
            return []

        # คำนวณ ATR
        atr = await calculate_atr(api_key, api_secret, symbol, timeframe, length=7)
        if atr is None:
            message(symbol, "ไม่สามารถคำนวณค่า ATR ได้", "red")
            return []
            
        # คำนวณเปอร์เซ็นต์ ATR เทียบกับราคา
        atr_percent = (atr / entry_price) * 100
        message(symbol, f"คำนวณ TP จาก: Entry: {entry_price}, ATR: {atr:.8f} ({atr_percent:.2f}%)", "blue")

        # คำนวณราคา TP โดยใช้ ATR เป็นฐาน และปรับด้วย PRICE_INCREASE/DECREASE
        tp_prices = {}
        if position_side == 'buy':
            tp_base2 = entry_price + (atr * 2)
            tp_base3 = entry_price + (atr * 3)
            tp_base4 = entry_price + (atr * 4)
            
            # ปรับด้วย PRICE_INCREASE แบบเดิม ไม่คูณเพิ่ม
            tp_prices['tp2'] = tp_base2 * (PRICE_INCREASE + (PRICE_CHANGE_THRESHOLD * 4))
            tp_prices['tp3'] = tp_base3 * (PRICE_INCREASE + (PRICE_CHANGE_THRESHOLD * 6))
            tp_prices['tp4'] = tp_base4 * (PRICE_INCREASE + (PRICE_CHANGE_THRESHOLD * 8))
        else:  # sell
            tp_base2 = entry_price - (atr * 2)
            tp_base3 = entry_price - (atr * 3)
            tp_base4 = entry_price - (atr * 4)
            
            # ปรับด้วย PRICE_DECREASE แบบเดิม ไม่คูณเพิ่ม
            tp_prices['tp2'] = tp_base2 * (PRICE_DECREASE - (PRICE_CHANGE_THRESHOLD * 4))
            tp_prices['tp3'] = tp_base3 * (PRICE_DECREASE - (PRICE_CHANGE_THRESHOLD * 6))
            tp_prices['tp4'] = tp_base4 * (PRICE_DECREASE - (PRICE_CHANGE_THRESHOLD * 8))

        # แสดงราคาฐานก่อนปรับ
        message(symbol, f"Entry: {entry_price:.8f}", "blue")
        message(symbol, "ราคา Take Profit ฐาน (ก่อนปรับ):", "blue")
        base_prices = {'tp2': tp_base2, 'tp3': tp_base3, 'tp4': tp_base4}
        for level, price in base_prices.items():
            distance_in_atr = abs(price - entry_price) / atr
            message(symbol, f"{level} base: {price:.8f} ({distance_in_atr:.1f} ATR)", "blue")

        # แสดงราคา TP หลังปรับ
        message(symbol, "ราคา Take Profit หลังปรับ:", "blue")
        for level, price in tp_prices.items():
            profit_percent = abs((price - entry_price) / entry_price * 100)
            distance_in_atr = abs(price - entry_price) / atr
            multiplier = (PRICE_INCREASE if position_side == 'buy' else PRICE_DECREASE) ** (int(level[-1]))
            message(symbol, f"{level}: {price:.8f} ({profit_percent:.2f}%, {distance_in_atr:.1f} ATR, x{multiplier:.4f})", "blue")

        # ตรวจสอบและปรับราคาตามข้อจำกัดของ exchange
        for tp_level in tp_prices:
            adjusted_price = await get_adjusted_price(api_key, api_secret, str(tp_prices[tp_level]), entry_price, position_side, symbol)
            if adjusted_price is not None:
                tp_prices[tp_level] = adjusted_price
            else:
                message(symbol, f"ไม่สามารถปรับราคา {tp_level} ได้", "red")
                return []

        # สร้าง orders
        orders = []
        order_quantities = {
            'tp2': '20%',
            'tp3': '25%',
            'tp4': '25%'
        }

        for tp_level, quantity in order_quantities.items():
            side = 'sell' if position_side == 'buy' else 'buy'
            tp_order = await create_order(
                api_key, api_secret,
                symbol=symbol,
                side=side,
                price=str(tp_prices[tp_level]),
                quantity=quantity,
                order_type='TAKE_PROFIT_MARKET'
            )

            if tp_order:
                orders.append(tp_order)
                message(symbol, f"ตั้ง {tp_level} ({quantity}) ที่ราคา {tp_prices[tp_level]:.8f}", "cyan")
            else:
                message(symbol, f"ไม่สามารถสร้างคำสั่ง {tp_level} ได้", "red")

        return orders

    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"เกิดข้อผิดพลาดในการสร้าง Take Profit Orders: {str(e)}", "red")
        message(symbol, f"Error: {error_traceback}", "red")
        return []
    
async def manage_position_profit(api_key: str, api_secret: str, symbol: str, state: SymbolState):
    """จัดการ position profit โดยเฉพาะการย้าย stoploss ไปที่จุดเข้าเมื่อถึง TP1"""
    exchange = None
    try:
        # ตรวจสอบเงื่อนไขเบื้องต้น
        if not state.is_in_position:
            return

        # สร้าง exchange instance
        exchange = await create_future_exchange(api_key, api_secret)

        # ดึงข้อมูลที่จำเป็น
        data_tasks = [
            get_future_market_price(api_key, api_secret, symbol),
            get_current_stoploss(api_key, api_secret, symbol),
            calculate_atr(api_key, api_secret, symbol, state.config.timeframe, length=7)
        ]
        data_results = await asyncio.gather(*data_tasks)
        current_price = data_results[0]
        current_stoploss = data_results[1]
        atr = data_results[2]

        # ตรวจสอบข้อมูลที่จำเป็น
        if current_price is None:
            message(symbol, "ไม่สามารถดึงราคาปัจจุบันได้", "yellow")
            return
            
        if current_stoploss is None:
            message(symbol, "ไม่สามารถดึงค่า stoploss ปัจจุบันได้", "yellow")
            return
            
        if atr is None:
            message(symbol, "ไม่สามารถคำนวณค่า ATR ได้", "yellow")
            return

        entry_price = state.global_entry_price
        
        # คำนวณกำไรปัจจุบันในหน่วย ATR
        if state.global_position_side == 'buy':
            current_profit_atr = (current_price - entry_price) / (atr * (PRICE_INCREASE + (PRICE_CHANGE_THRESHOLD * 2)))
            current_profit_percent = ((current_price - entry_price) / entry_price) * 100
        else:  # sell
            current_profit_atr = (entry_price - current_price) / (atr * (PRICE_INCREASE + (PRICE_CHANGE_THRESHOLD * 2)))
            current_profit_percent = ((entry_price - current_price) / entry_price) * 100

        # จัดการ TP1 - ย้าย stoploss ไปที่จุดเข้าเมื่อกำไรถึง 1 ATR
        if current_profit_atr >= 1 and not state.tp_levels_hit['tp1']:
            message(symbol, f"กำไรถึงระดับ 1 ({current_profit_atr:.2f} ATR, {current_profit_percent:.2f}%) - ปรับ stoploss", "cyan")
            
            try:
                # เลื่อน stoploss มาที่จุดเข้า
                if state.global_position_side == 'buy':
                    new_stoploss = entry_price * PRICE_DECREASE
                    if current_stoploss < new_stoploss:
                        message(symbol, f"กำลังปรับ stoploss ไปที่จุดเข้า {new_stoploss:.8f}", "cyan")
                        await change_stoploss_to_price(api_key, api_secret, symbol, new_stoploss)
                        state.tp_levels_hit['tp1'] = True
                        message(symbol, "ปรับ stoploss เรียบร้อย", "cyan")
                else:  # sell
                    new_stoploss = entry_price * PRICE_INCREASE
                    if current_stoploss > new_stoploss:
                        message(symbol, f"กำลังปรับ stoploss ไปที่จุดเข้า {new_stoploss:.8f}", "cyan")
                        await change_stoploss_to_price(api_key, api_secret, symbol, new_stoploss)
                        state.tp_levels_hit['tp1'] = True
                        message(symbol, "ปรับ stoploss เรียบร้อย", "cyan")

            except Exception as e:
                message(symbol, f"เกิดข้อผิดพลาดในการปรับ stoploss: {str(e)}", "red")

    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"เกิดข้อผิดพลาดในการจัดการกำไร: {str(e)}", "red")
        message(symbol, f"Error: {error_traceback}", "red")
    finally:
        if exchange:
            try:
                await exchange.close()
            except:
                pass
 
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
    """จัดการการปิด position และจัดการการเข้า position ใหม่ถ้าอยู่ในเงื่อนไข"""
    try:
        message(symbol, f"Position ถูกปิด!", "red")
        
        # ล้าง orders ทั้งหมดก่อน
        await clear_all_orders(api_key, api_secret, symbol)
        state.reset_position_state()

        # บันทึกการเทรด
        await record_trade(api_key, api_secret, symbol,
                        'BUY' if state.global_position_side == 'buy' else 'SELL',
                        state.global_entry_price, price, state.config.entry_amount,
                        f'Close Position', 
                        state)

        # ตรวจสอบเงื่อนไขการเข้า position ใหม่
        if (state.last_focus_price or state.is_wait_candle) and state.last_candle_cross and 'candle' in state.last_candle_cross:
            message(symbol, "กำลังตรวจสอบเงื่อนไขการเข้า position ใหม่...", "yellow")
            cross_candle = state.last_candle_cross['candle']
            state.last_focus_price = None
            state.is_wait_candle = None

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
            should_market_entry = price_diff_percent < PRICE_CHANGE_MAXPERCENT  # ถ้าราคาต่างไม่เกิน 2%
            
            if (entry_side == 'buy' and price <= entry_trigger_price) or \
               (entry_side == 'sell' and price >= entry_trigger_price) or \
               should_market_entry:
                
                try:
                    # คำนวณ quantity เริ่มต้น
                    entry_price = price if should_market_entry else entry_trigger_price
                    initial_quantity = await get_adjusted_quantity(
                        api_key, api_secret,
                        symbol=symbol,
                        price=entry_price,
                        quantity=state.config.entry_amount
                    )
                    if initial_quantity is None:
                        message(symbol, "ไม่สามารถคำนวณปริมาณได้", "red")
                        return

                    # ปรับ quantity ตาม stoploss
                    adjusted_quantity = await adjust_quantity_for_stoploss(
                        api_key, api_secret, symbol,
                        entry_price, stoploss_price,
                        initial_quantity, state
                    )

                    entry_order = None
                    if should_market_entry:
                        # เข้าด้วย MARKET order ถ้าราคาต่างไม่เกิน 2%
                        message(symbol, f"ราคาต่างจากจุด trigger {price_diff_percent:.2f}% - เข้าด้วย MARKET", "yellow")
                        entry_order = await create_order(
                            api_key, api_secret,
                            symbol=symbol,
                            side=entry_side,
                            price='now',
                            quantity=str(adjusted_quantity),
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
                            quantity=str(adjusted_quantity),
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
                                
                                # อัพเดทสถานะสำหรับ market entry
                                state.is_in_position = True
                                state.global_entry_price = float(entry_order['average'])
                                state.global_position_entry_time = datetime.now(pytz.UTC)
                                state.global_position_side = entry_side
                                state.entry_candle = await get_current_candle(api_key, api_secret, symbol, state.config.timeframe)
                                
                                # สร้าง Take Profit Orders สำหรับ market entry
                                await setup_take_profit_orders(
                                    api_key, api_secret, symbol,
                                    state.global_entry_price,
                                    state.global_position_side,
                                    state.config.timeframe
                                )
                                
                                # รีเซ็ตข้อมูล entry orders
                                state.entry_orders = None
                                state.entry_side = None
                                state.entry_price = None
                                state.entry_stoploss_price = None
                            else:
                                # อัพเดทสถานะสำหรับ pending entry
                                state.entry_side = entry_side
                                state.entry_price = entry_trigger_price
                                state.entry_stoploss_price = stoploss_price
                                state.entry_orders = {
                                    'entry_order': entry_order,
                                    'stoploss_order': stoploss_order,
                                    'is_market_entry': should_market_entry
                                }
                                
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
            state.save_state()
            
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
            # ส่วนจัดการ position ที่มีอยู่
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
                        await change_stoploss_to_price(api_key, api_secret, symbol, state.last_focus_price)
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
                    should_market_entry = current_price > entry_trigger_price
                else:  # crossunder
                    entry_trigger_price = float(cross_candle.get('low')) * PRICE_DECREASE
                    stoploss_price = float(cross_candle.get('high')) * PRICE_INCREASE
                    entry_side = 'sell'
                    stoploss_side = 'buy'
                    should_market_entry = current_price < entry_trigger_price

                try:
                    # คำนวณ quantity เริ่มต้น
                    entry_price = current_price if should_market_entry else entry_trigger_price
                    initial_quantity = await get_adjusted_quantity(
                        api_key, api_secret,
                        symbol=symbol,
                        price=entry_price,
                        quantity=state.config.entry_amount
                    )
                    if initial_quantity is None:
                        message(symbol, "ไม่สามารถคำนวณปริมาณได้", "red")
                        return

                    # ปรับ quantity ตาม stoploss
                    adjusted_quantity = await adjust_quantity_for_stoploss(
                        api_key, api_secret, symbol,
                        entry_price, stoploss_price,
                        initial_quantity, state
                    )

                    entry_order = None
                    if should_market_entry:
                        message(symbol, f"ราคาผ่านจุด trigger แล้ว ({current_price:.8f} vs {entry_trigger_price:.8f})", "yellow")
                        message(symbol, f"เข้า position ด้วย MARKET order", "yellow")
                        
                        entry_order = await create_order(
                            api_key, api_secret,
                            symbol=symbol,
                            side=entry_side,
                            price='now',
                            quantity=str(adjusted_quantity),
                            order_type='MARKET'
                        )
                    else:
                        entry_order = await create_order(
                            api_key, api_secret,
                            symbol=symbol,
                            side=entry_side,
                            price=str(entry_trigger_price),
                            quantity=str(adjusted_quantity),
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
                            # อัพเดทสถานะพื้นฐาน
                            state.entry_side = entry_side
                            state.entry_price = entry_trigger_price
                            state.entry_stoploss_price = stoploss_price
                            state.entry_orders = {
                                'entry_order': entry_order,
                                'stoploss_order': stoploss_order,
                                'is_market_entry': should_market_entry
                            }

                            if should_market_entry:
                                message(symbol, f"เข้า {entry_side.upper()} ด้วย MARKET ORDER สำเร็จ", "green")
                                state.reset_position_state()
                                # อัพเดทสถานะสำหรับ market entry
                                state.is_in_position = True
                                if 'average' in entry_order and entry_order['average']:
                                    state.global_entry_price = float(entry_order['average'])
                                else:
                                    state.global_entry_price = current_price
                                state.global_position_entry_time = datetime.now(pytz.UTC)
                                state.global_position_side = entry_side
                                
                                # ดึงข้อมูลแท่งเทียนและตั้ง TP
                                current_candle = await get_current_candle(api_key, api_secret, symbol, state.config.timeframe)
                                if current_candle:
                                    state.entry_candle = current_candle
                                    await setup_take_profit_orders(
                                        api_key, api_secret, symbol,
                                        state.global_entry_price,
                                        state.global_position_side,
                                        state.config.timeframe
                                    )
                                else:
                                    message(symbol, "ไม่สามารถดึงข้อมูลแท่งเทียนสำหรับตั้ง TP ได้", "red")
                            else:
                                message(symbol, f"ตั้งคำสั่ง {entry_side.upper()} STOP_MARKET ที่ราคา {entry_trigger_price:.8f}", "blue")
                            
                            state.save_state()
                        else:
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
            state.reset_position_state()
            # อัพเดทสถานะ position
            state.is_in_position = True
            state.global_entry_price = float(entry_order_status['average'])
            state.global_position_entry_time = datetime.now(pytz.UTC)
            state.global_position_side = state.entry_side
            
            # ดึงข้อมูลแท่งเทียนและตั้ง TP
            current_candle = await get_current_candle(api_key, api_secret, symbol, state.config.timeframe)
            if state.last_candle_cross['candle'] and current_candle:
                state.entry_candle = current_candle
                # สร้าง Take Profit Orders
                await setup_take_profit_orders(
                    api_key, api_secret, symbol,
                    state.global_entry_price,
                    state.global_position_side,
                    state.config.timeframe
                )
                # แสดงเป้าหมายการทำกำไร
                await _show_profit_targets(symbol, float(current_candle['high']), float(current_candle['low']))
            else:
                message(symbol, "ไม่สามารถดึงข้อมูลแท่งเทียนสำหรับตั้ง TP ได้", "red")
            
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
                state.reset_position_state()
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

        # ตรวจสอบเงื่อนไขการ swap
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

            state.is_swapping = True
            old_entry_price = state.global_entry_price
            old_side = state.global_position_side

            # ดำเนินการ swap และสร้าง orders แบบขนาน
            swap_tasks = [
                swap_position_side(api_key, api_secret, symbol),
                clear_all_orders(api_key, api_secret, symbol)  # ต้องใช้ clear_all_orders เพราะต้องลบ TP orders ด้วย
            ]
            await asyncio.gather(*swap_tasks)

            # สร้าง stoploss order ใหม่
            stoploss_order = await create_order(
                api_key, api_secret, symbol=symbol,
                side='buy' if new_side == 'sell' else 'sell',
                price=str(new_stoploss),
                quantity='MAX',
                order_type='STOPLOSS_MARKET'
            )

            if stoploss_order:
                message(symbol, f"สลับ position จาก {position_side}", "magenta")
                state.reset_position_state()
                #message(symbol, f"ตั้งคำสั่ง Stoploss ที่ราคา {new_stoploss:.8f}", "blue")

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

                # สร้าง Take Profit Orders ใหม่
                await setup_take_profit_orders(
                    api_key, api_secret, symbol,
                    state.global_entry_price,
                    state.global_position_side,
                    state.config.timeframe
                )

                state.is_swapping = False
                state.last_focus_price = None
                state.entry_stoploss_price = None
                state.save_state()
            else:
                message(symbol, "ไม่สามารถสร้าง Stoploss Order ได้", "red")
                state.is_swapping = False

    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"Error in position swap handling: {str(e)}", "red")
        message(symbol, f"Error: {error_traceback}", "red")
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
        # โหลด Trading Config
        trading_config = await load_trading_config()
        if not trading_config:
            message("SYSTEM", "ไม่สามารถโหลด Trading Config ได้ กรุณาตรวจสอบไฟล์ index.json", "red")
            return
            
        # เริ่มต้น price tracker และ kline tracker (ทำครั้งเดียว)
        price_tracker = get_price_tracker()
        kline_tracker = get_kline_tracker()
        
        # สมัครและโหลดข้อมูลเริ่มต้นสำหรับทุกเหรียญ
        init_tasks = []
        symbol_configs = {}
        
        # อ่านค่าจาก index.json และตรวจสอบความถูกต้อง
        try:
            with open('json/index.json', 'r') as f:
                configs = json.load(f)
                for config in configs:
                    # ทำให้ symbol เป็นตัวพิมพ์ใหญ่เสมอ
                    symbol = config['symbol'].upper()
                    # ตรวจสอบว่ามี timeframe หรือไม่
                    if 'timeframe' not in config:
                        message("SYSTEM", f"ไม่พบ timeframe สำหรับ {symbol} ข้ามการทำงาน", "yellow")
                        continue

                    message("SYSTEM", f"กำลังโหลดข้อมูล {symbol} ({config['timeframe']})", "blue")
                    symbol_configs[symbol] = config
                    clean_symbol = symbol.lower()
                    price_tracker.subscribe_symbol(clean_symbol)
                    init_tasks.append(kline_tracker.initialize_symbol_data(symbol, config['timeframe']))
        except FileNotFoundError:
            message("SYSTEM", "ไม่พบไฟล์ index.json", "red")
            return
        except json.JSONDecodeError:
            message("SYSTEM", "รูปแบบไฟล์ index.json ไม่ถูกต้อง", "red")
            return
        except Exception as e:
            message("SYSTEM", f"เกิดข้อผิดพลาดในการอ่านไฟล์ index.json: {str(e)}", "red")
            return

        if not symbol_configs:
            message("SYSTEM", "ไม่พบคู่เทรดที่ต้องการทำงาน กรุณาตรวจสอบไฟล์ index.json", "red")
            return
        
        # รอให้โหลดข้อมูลเริ่มต้นเสร็จ
        if init_tasks:
            message("SYSTEM", f"กำลังโหลดข้อมูลแท่งเทียนเริ่มต้น ({len(init_tasks)} symbols)...", "yellow")
            await asyncio.gather(*init_tasks)
            message("SYSTEM", "โหลดข้อมูลแท่งเทียนเริ่มต้นเสร็จสมบูรณ์", "green")
        
        # เริ่ม trackers
        tracker_tasks = [
            asyncio.create_task(price_tracker.start()),
            asyncio.create_task(kline_tracker.start())
        ]
        
        # รอให้ trackers เริ่มต้นเสร็จ
        await asyncio.sleep(2)
        
        # อัพเดท symbol data ครั้งเดียว
        await update_symbol_data(api_key, api_secret)
        
        # สร้าง trading tasks
        trading_tasks = []
        symbol_states = {}
        
        for symbol, config in symbol_configs.items():
            try:
                state = SymbolState(symbol)
                symbol_states[symbol] = state
                main_coro = run_bot_wrapper(api_key, api_secret, symbol, state)
                main_task = asyncio.create_task(run_with_error_handling(main_coro, symbol))
                trading_tasks.append(main_task)
                message("SYSTEM", f"เริ่มระบบเทรดสำหรับ {symbol} (Timeframe: {config['timeframe']})", "green")
            except Exception as e:
                error_traceback = traceback.format_exc()
                message("SYSTEM", f"ไม่สามารถเริ่มระบบเทรดสำหรับ {symbol}: {str(e)}", "red")
                message("SYSTEM", f"Error: {error_traceback}", "red")
        
        if not trading_tasks:
            message("SYSTEM", "ไม่มีระบบเทรดทำงานอยู่ กรุณาตรวจสอบการตั้งค่า", "red")
            return
        
        message("SYSTEM", f"เริ่มระบบเทรดทั้งหมด {len(trading_tasks)} คู่เทรด", "green")
        
        # รอให้ทุก task ทำงานเสร็จ
        all_tasks = tracker_tasks + trading_tasks
        await asyncio.gather(*all_tasks)
        
    except asyncio.CancelledError:
        message("SYSTEM", "ได้รับคำสั่งยกเลิกการทำงาน", "yellow")
    except KeyboardInterrupt:
        message("SYSTEM", "ได้รับคำสั่งปิดโปรแกรม กำลังปิดระบบ...", "yellow")
    except Exception as e:
        error_traceback = traceback.format_exc()
        message("SYSTEM", f"เกิดข้อผิดพลาดใน main: {str(e)}", "red")
        message("SYSTEM", f"Error: {error_traceback}", "red")
    finally:
        message("SYSTEM", "กำลังปิดระบบ...", "yellow")
        
        # ยกเลิกทุก task
        for task in (tracker_tasks + trading_tasks):
            if not task.done():
                task.cancel()
        
        # หยุด trackers
        if price_tracker:
            await price_tracker.stop()
        if kline_tracker:
            await kline_tracker.stop()
        
        # รอให้ทุก task ถูกยกเลิกเสร็จสิ้น
        try:
            await asyncio.gather(*(tracker_tasks + trading_tasks), return_exceptions=True)
        except Exception as e:
            error_traceback = traceback.format_exc()
            message("SYSTEM", f"เกิดข้อผิดพลาดขณะปิดระบบ: {str(e)}", "red")
            message("SYSTEM", f"Error: {error_traceback}", "red")
        
        message("SYSTEM", "ปิดระบบเรียบร้อย", "green")

if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        message("SYSTEM", "ปิดโปรแกรมโดยผู้ใช้", "yellow")
    except Exception as e:
        error_traceback = traceback.format_exc()
        message("SYSTEM", f"เกิดข้อผิดพลาดร้ายแรง: {str(e)}", "red")
        message("SYSTEM", f"Error: {error_traceback}", "red")
    finally:
        pending = asyncio.all_tasks(loop=loop)
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()
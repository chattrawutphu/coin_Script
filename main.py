import asyncio
from datetime import datetime, timedelta
import json
import os
import time
import traceback
from functools import wraps
import pytz
import pandas as pd
import numpy as np

from function.binance.futures.check.check_position import check_position
from function.binance.futures.check.check_server_status import check_server_status
from function.binance.futures.check.check_user_api_status import check_user_api_status
from function.binance.futures.order.change_stoploss_to_price import change_stoploss_to_price
from function.binance.futures.order.create_order import create_order, get_adjusted_quantity
from function.binance.futures.order.get_all_order import clear_all_orders, clear_stoploss, clear_tp_orders
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
from config import DEFAULT_CONFIG, MIN_NOTIONAL, PRICE_CHANGE_MAXPERCENT, PRICE_CHANGE_THRESHOLD, api_key, api_secret
from config import (
    TRADING_CONFIG,
    PRICE_INCREASE,
    PRICE_DECREASE,
)

class SymbolState:
    """คลาสสำหรับจัดการสถานะของแต่ละเหรียญ แบบ optimized"""
    def __init__(self, symbol: str):
        # Base configuration
        self.symbol = symbol
        self.config = TradingConfig(symbol)
        self.state_file = f'json/state/{symbol}.json'
        self.trade_record_file = f'json/trade_records/{symbol}.json'
        
        # Market data cache
        self.current_orders = []
        self.current_candle = None
        self.current_price = None
        self.current_stoploss = None
        self.current_market_data = {
            'ohlcv': None,
            'last_update': None,
            'position_side': None,
            'available_balance': None,
            'atr': None,
            'atr_last_update': None
        }
        self.current_rsi_period = None
        self.current_atr_length_1 = None
        self.current_atr_length_2 = None
        self.current_atr_tp = None
        self.last_checked_candle = None
        
        # Position tracking
        self.is_in_position = False
        self.is_swapping = False
        self.is_wait_candle = False
        self.global_position_data = {
            'entry_price': None,
            'entry_time': None,
            'position_side': None,
            'position_size': None,
            'leverage': None,
            'margin_type': None
        }
        
        # Order tracking
        self.entry_orders = None
        self.entry_side = None
        self.entry_price = None
        self.entry_stoploss_price = None
        
        # Candle tracking
        self.last_candle_time = None
        self.last_candle_cross = None
        self.entry_candle = None
        
        # Price focus points
        self.last_focus_price = None
        self.last_focus_stopprice = None
        
        # Take profit management
        self.tp_levels_hit = {
            'tp1': False,
            'tp2': False,
            'tp3': False,
            'tp4': False
        }

        # Martingale tracking
        self.martingale_multiplier = 1.0
        self.consecutive_losses = 0
        
        # Performance metrics
        self.performance_data = {
            'trades_count': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'total_profit': 0,
            'total_fees': 0,
            'start_time': None,
            'largest_profit': 0,
            'largest_loss': 0
        }

    def reset_order_state(self):
        """รีเซ็ตสถานะที่เกี่ยวข้องกับ orders"""
        self.entry_orders = None
        self.entry_side = None
        self.entry_price = None
        self.entry_stoploss_price = None
        self.last_checked_candle = None

    async def update_market_data(self, api_key: str, api_secret: str):
        """อัพเดทข้อมูลตลาดทั้งหมดในครั้งเดียว"""
        try:
            # Fetch all market data concurrently
            tasks = [
                get_future_market_price(api_key, api_secret, self.symbol),
                get_current_stoploss(api_key, api_secret, self.symbol, self),
                get_position_side(api_key, api_secret, self.symbol),
                get_future_available_balance(api_key, api_secret),
                get_current_candle(api_key, api_secret, self.symbol, self.config.timeframe),
                self._fetch_current_orders(api_key, api_secret)
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Update cache
            self.current_price = results[0] if not isinstance(results[0], Exception) else self.current_price
            self.current_stoploss = results[1] if not isinstance(results[1], Exception) else self.current_stoploss
            
            self.current_market_data.update({
                'position_side': results[2] if not isinstance(results[2], Exception) else self.current_market_data['position_side'],
                'available_balance': results[3] if not isinstance(results[3], Exception) else self.current_market_data['available_balance'],
                'ohlcv': results[4] if not isinstance(results[4], Exception) else self.current_market_data['ohlcv'],
                'last_update': datetime.now(pytz.UTC)
            })
            
            self.current_candle = results[4] if not isinstance(results[4], Exception) else self.current_candle
            self.current_orders = results[5] if not isinstance(results[5], Exception) else []
                
            return True
            
        except Exception as e:
            message(self.symbol, f"Error updating market data: {str(e)}", "red")
            return False
    
    async def _fetch_current_orders(self, api_key: str, api_secret: str):
        """ดึงข้อมูล orders ปัจจุบัน"""
        try:
            exchange = await create_future_exchange(api_key, api_secret)
            orders = await exchange.fetch_open_orders(self.symbol)
            await exchange.close()
            return orders
        except Exception as e:
            message(self.symbol, f"Error fetching orders: {str(e)}", "red")
            return []
    
    def update_position_data(self, position_info: dict):
        """อัพเดทข้อมูล position ทั้งหมดในครั้งเดียว"""
        if position_info:
            self.global_position_data.update({
                'entry_price': float(position_info.get('entryPrice', 0)),
                'position_side': position_info.get('positionSide', None),
                'position_size': float(position_info.get('positionAmt', 0)),
                'leverage': int(position_info.get('leverage', 20)),
                'margin_type': position_info.get('marginType', 'cross')
            })
            self.is_in_position = abs(self.global_position_data['position_size']) > 0
        else:
            self.reset_position_data()

    def reset_position_data(self):
        """รีเซ็ตข้อมูล position ทั้งหมด"""
        self.is_in_position = False
        self.global_position_data = {
            'entry_price': None,
            'entry_time': None,
            'position_side': None,
            'position_size': None,
            'leverage': None,
            'margin_type': None
        }
        self.tp_levels_hit = {
            'tp1': False,
            'tp2': False,
            'tp3': False,
            'tp4': False
        }

    def save_state(self):
        """บันทึกสถานะทั้งหมดลงไฟล์"""
        def datetime_to_iso(dt):
            """แปลง datetime เป็น ISO format string"""
            if isinstance(dt, datetime):
                return dt.isoformat()
            return dt

        def process_dict(d):
            """แปลงค่าใน dictionary"""
            if not isinstance(d, dict):
                return d
            return {k: datetime_to_iso(v) if isinstance(v, datetime) else process_dict(v) 
                for k, v in d.items()}

        try:
            current_state = {
                'current_orders': self.current_orders,
                'current_candle': self.current_candle,
                'current_price': self.current_price,
                'current_stoploss': self.current_stoploss,
                'current_market_data': process_dict(self.current_market_data),
                'current_rsi_period': self.current_rsi_period,
                'current_atr_length_1': self.current_atr_length_1,
                'current_atr_length_2': self.current_atr_length_2,
                'current_atr_tp': self.current_atr_tp,  # เพิ่ม ATR 7
                'last_checked_candle': self.last_checked_candle,
                'is_in_position': self.is_in_position,
                'is_swapping': self.is_swapping,
                'is_wait_candle': self.is_wait_candle,
                'global_position_data': process_dict(self.global_position_data),
                'entry_orders': self.entry_orders,
                'entry_side': self.entry_side,
                'entry_price': self.entry_price,
                'entry_stoploss_price': self.entry_stoploss_price,
                'last_candle_time': datetime_to_iso(self.last_candle_time),
                'last_candle_cross': self.last_candle_cross,
                'entry_candle': self.entry_candle,
                'last_focus_price': self.last_focus_price,
                'last_focus_stopprice': self.last_focus_stopprice,
                'tp_levels_hit': self.tp_levels_hit,
                'martingale_multiplier': self.martingale_multiplier,
                'consecutive_losses': self.consecutive_losses,
                'performance_data': process_dict(self.performance_data)
            }
            
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            with open(self.state_file, 'w') as f:
                json.dump(current_state, f, indent=2)

        except Exception as e:
            error_traceback = traceback.format_exc()
            message(self.symbol, f"เกิดข้อผิดพลาดในการบันทึกสถานะ: {str(e)}", "red")
            message(self.symbol, f"Error: {error_traceback}", "red")

    def load_state(self):
        """โหลดสถานะทั้งหมดจากไฟล์"""
        try:
            # ตรวจสอบไฟล์มีอยู่จริง
            if not os.path.exists(self.state_file):
                message(self.symbol, f"ไม่พบไฟล์สถานะ เริ่มต้นด้วยค่าเริ่มต้น", "yellow")
                return False

            # พยายามอ่านไฟล์
            try:
                with open(self.state_file, 'r') as f:
                    saved_state = json.load(f)
            except json.JSONDecodeError:
                message(self.symbol, f"ไฟล์สถานะเสียหาย ลบไฟล์เดิมและเริ่มใหม่", "yellow")
                os.remove(self.state_file)
                return False
                    
            def parse_datetime(dt_str):
                """แปลง ISO format string กลับเป็น datetime"""
                if dt_str and isinstance(dt_str, str):
                    try:
                        return datetime.fromisoformat(dt_str)
                    except:
                        return dt_str
                return dt_str

            def process_dict(d):
                """แปลงค่าใน dictionary"""
                if not isinstance(d, dict):
                    return d
                return {k: parse_datetime(v) if k.endswith('_time') or k.endswith('_update') 
                    else process_dict(v) for k, v in d.items()}
            
            # Reset state ก่อนโหลดค่าใหม่
            self._initialize_state()
            
            # Load state values with validation
            try:
                # Load current market data
                if 'current_market_data' in saved_state:
                    self.current_market_data = process_dict(saved_state['current_market_data'])
                self.current_orders = saved_state.get('current_orders', [])
                self.current_candle = saved_state.get('current_candle')
                self.current_price = saved_state.get('current_price')
                self.current_stoploss = saved_state.get('current_stoploss')
                self.current_rsi_period = saved_state.get('current_rsi_period')
                self.current_atr_length_1 = saved_state.get('current_atr_length_1')
                self.current_atr_length_2 = saved_state.get('current_atr_length_2')
                self.current_atr_tp = saved_state.get('current_atr_tp')  # โหลด ATR 7
                self.last_checked_candle = saved_state.get('last_checked_candle')
                
                # Load position states
                self.is_in_position = saved_state.get('is_in_position', False)
                self.is_swapping = saved_state.get('is_swapping', False)
                self.is_wait_candle = saved_state.get('is_wait_candle', False)
                
                if 'global_position_data' in saved_state:
                    self.global_position_data = process_dict(saved_state['global_position_data'])
                
                # Load order states
                self.entry_orders = saved_state.get('entry_orders')
                self.entry_side = saved_state.get('entry_side')
                self.entry_price = saved_state.get('entry_price')
                self.entry_stoploss_price = saved_state.get('entry_stoploss_price')
                
                # Load candle data
                self.last_candle_time = parse_datetime(saved_state.get('last_candle_time'))
                self.last_candle_cross = saved_state.get('last_candle_cross')
                self.entry_candle = saved_state.get('entry_candle')
                
                # Load price focus points
                self.last_focus_price = saved_state.get('last_focus_price')
                self.last_focus_stopprice = saved_state.get('last_focus_stopprice')
                
                # Load TP states
                self.tp_levels_hit = saved_state.get('tp_levels_hit', {})
                
                # Load Martingale state
                self.martingale_multiplier = saved_state.get('martingale_multiplier', 1.0)
                self.consecutive_losses = saved_state.get('consecutive_losses', 0)
                # Load performance data
                if 'performance_data' in saved_state:
                    self.performance_data = process_dict(saved_state['performance_data'])
                
                return True
                
            except Exception as e:
                error_traceback = traceback.format_exc()
                message(self.symbol, f"เกิดข้อผิดพลาดในการแปลงข้อมูล: {str(e)}", "red")
                message(self.symbol, f"Error: {error_traceback}", "red")
                
                # ถ้าเกิดข้อผิดพลาดให้ลบไฟล์เดิมและเริ่มใหม่
                os.remove(self.state_file)
                self._initialize_state()
                return False
                
        except Exception as e:
            error_traceback = traceback.format_exc()
            message(self.symbol, f"เกิดข้อผิดพลาดในการโหลดสถานะ: {str(e)}", "red")
            message(self.symbol, f"Error: {error_traceback}", "red")
            return False
    
    def _initialize_state(self):
        """รีเซ็ตค่าเริ่มต้นของ state"""
        # Market data cache
        self.current_orders = []
        self.current_candle = None
        self.current_price = None
        self.current_stoploss = None
        self.current_market_data = {
            'ohlcv': None,
            'last_update': None,
            'position_side': None,
            'available_balance': None,
            'atr': None,
            'atr_last_update': None,
            'atr_cache': {}
        }
        self.current_rsi_period = None
        self.current_atr_length_1 = None
        self.current_atr_length_2 = None
        self.current_atr_tp = None
        
        # Position tracking
        self.is_in_position = False
        self.is_swapping = False
        self.is_wait_candle = False
        self.global_position_data = {
            'entry_price': None,
            'entry_time': None,
            'position_side': None,
            'position_size': None,
            'leverage': None,
            'margin_type': None
        }
        
        # Order tracking
        self.entry_orders = None
        self.entry_side = None
        self.entry_price = None
        self.entry_stoploss_price = None
        
        # Candle tracking
        self.last_candle_time = None
        self.last_candle_cross = None
        self.entry_candle = None
        
        # Price focus points
        self.last_focus_price = None
        self.last_focus_stopprice = None
        
        # Take profit tracking
        self.tp_levels_hit = {}

        # Reset Martingale state
        self.martingale_multiplier = 1.0
        self.consecutive_losses = 0
        
        # Performance metrics
        self.performance_data = {
            'trades_count': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'total_profit': 0,
            'total_fees': 0,
            'start_time': None,
            'largest_profit': 0,
            'largest_loss': 0
        }
    
class TradingConfig:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self._load_config()
        
    # แก้ไขส่วน TradingConfig.__init__ เพิ่ม config ใหม่
    def _load_config(self):
        try:
            symbol_config = None
            
            # Try to load from index.json first
            if os.path.exists('json/index.json'):
                with open('json/index.json', 'r') as f:
                    config_list = json.load(f)
                    for config in config_list:
                        if isinstance(config, dict) and 'symbol' in config and config['symbol'] == self.symbol:
                            symbol_config = config
                            break

            # If not found in index.json, look in TRADING_CONFIG
            if not symbol_config:
                for config in TRADING_CONFIG:
                    if isinstance(config, dict) and 'symbol' in config and config['symbol'] == self.symbol:
                        symbol_config = config
                        break
                
            if symbol_config:
                # Load specific settings from config
                self.timeframe = symbol_config.get('timeframe', '4h')
                self.entry_amount = symbol_config.get('entry_amount', '50$')
                self.rsi_period = symbol_config.get('rsi_period', 7)
                self.rsi_overbought = symbol_config.get('rsi_overbought', 68)
                self.rsi_oversold = symbol_config.get('rsi_oversold', 32)
                self.min_stoploss = symbol_config.get('min_stoploss', None)
                self.max_stoploss = symbol_config.get('max_stoploss', None)
                self.fix_stoploss = symbol_config.get('fix_stoploss', 2)
                
                # เพิ่ม config ใหม่สำหรับ dynamic take profit
                tp_config = symbol_config.get('take_profits', {})
                self.take_profits = {
                    'move_sl_to_entry_at_tp1': tp_config.get('move_sl_to_entry_at_tp1', True),
                    'use_dynamic_tp': tp_config.get('use_dynamic_tp', True),  # เพิ่มตัวเลือกเปิด/ปิด dynamic TP
                    'average_with_entry': tp_config.get('average_with_entry', True),  # เพิ่มตัวเลือกการใช้ค่าเฉลี่ย
                    'levels': tp_config.get('levels', [
                        {'id': 'tp1', 'size': '5%', 'target_atr': 1},
                        {'id': 'tp2', 'size': '20%', 'target_atr': 2},
                        {'id': 'tp3', 'size': '25%', 'target_atr': 3},
                        {'id': 'tp4', 'size': '25%', 'target_atr': 4}
                    ])
                }

                # Martingale configuration
                martingale_config = symbol_config.get('martingale', {})
                self.martingale_enabled = martingale_config.get('enabled', False)
                self.martingale_max_multiplier = martingale_config.get('max_multiplier', 3.0)
                self.martingale_step = martingale_config.get('step', 0.5)
                self.martingale_reset_on_win = martingale_config.get('reset_on_win', True)
                
            else:
                # Use default settings
                message(self.symbol, f"ไม่พบการตั้งค่าสำหรับ {self.symbol} ใช้ค่า default", "yellow")
                self.timeframe = DEFAULT_CONFIG['timeframe']
                self.entry_amount = DEFAULT_CONFIG['entry_amount']
                self.rsi_period = DEFAULT_CONFIG['rsi_period']
                self.rsi_overbought = DEFAULT_CONFIG['rsi_overbought']
                self.rsi_oversold = DEFAULT_CONFIG['rsi_oversold']
                self.min_stoploss = None
                self.max_stoploss = None
                self.fix_stoploss = DEFAULT_CONFIG['fix_stoploss']
                self.take_profits = DEFAULT_CONFIG['take_profits']

        except Exception as e:
            error_traceback = traceback.format_exc()
            message(self.symbol, f"เกิดข้อผิดพลาดในการโหลด config: {str(e)}", "red")
            message(self.symbol, f"Error: {error_traceback}", "red")
            # Use default settings on error
            self.timeframe = DEFAULT_CONFIG['timeframe']
            self.entry_amount = DEFAULT_CONFIG['entry_amount']
            self.rsi_period = DEFAULT_CONFIG['rsi_period']
            self.rsi_overbought = DEFAULT_CONFIG['rsi_overbought']
            self.rsi_oversold = DEFAULT_CONFIG['rsi_oversold']
            self.min_stoploss = None
            self.max_stoploss = None
            self.fix_stoploss = DEFAULT_CONFIG['fix_stoploss']
            self.take_profits = DEFAULT_CONFIG['take_profits']
            
async def run_sequential_bot(api_key: str, api_secret: str, symbol: str, state: SymbolState):
    """ฟังก์ชันหลักสำหรับการเทรดของแต่ละเหรียญแบบทำงานตามลำดับ"""
    exchange = None
    try:
        state.load_state()
        exchange = await create_future_exchange(api_key, api_secret)

        if not await update_market_indicators(api_key, api_secret, symbol, state):
            message(symbol, "ไม่สามารถอัพเดทค่าตลาดได้ ข้ามรอบนี้", "yellow")
            return
        
        # อัพเดทข้อมูลตลาดทั้งหมดในครั้งเดียว
        await state.update_market_data(api_key, api_secret)
        
        # ตรวจสอบและดำเนินการตามสถานะปัจจุบัน
        if state.current_price is None:
            message(symbol, "ไม่สามารถดึงราคาตลาดได้ ข้ามรอบนี้", "yellow")
            return

        # Position management
        if state.is_in_position and not state.is_swapping:
            # ตรวจสอบว่ายังมี position อยู่จริง
            if not await check_position(api_key, api_secret, symbol):
                await _handle_position_close(api_key, api_secret, symbol, state, state.current_price)
            else:
                # จัดการ position ที่มีอยู่ตามปกติ
                if state.is_wait_candle and state.current_market_data['position_side']:
                    await _handle_stoploss_adjustment(
                        api_key, api_secret, symbol, state,
                        state.current_market_data['position_side'],
                        state.current_price
                    )

                if state.last_focus_price is not None:
                    await _handle_position_swap(
                        api_key, api_secret, symbol, state,
                        state.current_price,
                        state.current_market_data['position_side']
                    )

        await manage_position_profit(api_key, api_secret, symbol, state)

        # Entry orders management
        if state.entry_orders:
            await _handle_entry_orders(api_key, api_secret, symbol, state, state.current_price, exchange)

        # Candle check and signals
        current_candle = state.current_candle
        if current_candle:
            ohlcv = await exchange.fetch_ohlcv(symbol, state.config.timeframe, limit=3)
            rsi_cross = await get_rsi_cross_last_candle(
                api_key, api_secret, symbol,
                state.config.timeframe,
                state
            )

            if ohlcv and len(ohlcv) >= 3:
                last_closed_candle = ohlcv[-2]
                bangkok_tz = pytz.timezone('Asia/Bangkok')
                last_closed_time = datetime.fromtimestamp(last_closed_candle[0] / 1000, tz=pytz.UTC).astimezone(bangkok_tz)

                if (state.last_candle_time is None or 
                    last_closed_time > state.last_candle_time.astimezone(bangkok_tz)):
                    
                    await _handle_new_candle(
                        api_key, api_secret, symbol, state, last_closed_time,
                        state.current_market_data['position_side'],
                        [last_closed_candle], rsi_cross
                    )
                    
            # เพิ่มการตรวจสอบและสร้าง stoploss หลังจากการตรวจสอบแท่งเทียน
            if state.is_in_position:
                await check_and_recreate_stoploss(api_key, api_secret, symbol, state)

        # บันทึกสถานะ
        state.save_state()

    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"เกิดข้อผิดพลาดในการประมวลผล {symbol}: {str(e)}", "red")
        message(symbol, f"Error: {error_traceback}", "red")
    finally:
        if exchange:
            await exchange.close()

async def _handle_position_close(api_key, api_secret, symbol, state, price):
    """จัดการการปิด position และจัดการการเข้า position ใหม่ถ้าอยู่ในเงื่อนไข"""
    try:
        message(symbol, f"Position ถูกปิด!", "red")
        
        # ล้าง orders ทั้งหมดก่อน
        await clear_all_orders(api_key, api_secret, symbol)

        # บันทึกการเทรด
        await record_trade(api_key, api_secret, symbol,
                        'BUY' if state.global_position_data['position_side'] == 'buy' else 'SELL',
                        state.global_position_data['entry_price'], price, state.config.entry_amount,
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
            should_market_entry = price_diff_percent < PRICE_CHANGE_MAXPERCENT

            # ตรวจสอบเงื่อนไขการเข้า position
            price_condition_met = ((entry_side == 'buy' and price >= entry_trigger_price) or
                                 (entry_side == 'sell' and price <= entry_trigger_price))

            if price_condition_met:
                try:
                    # คำนวณและปรับ quantity
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

                    adjusted_quantity = await adjust_quantity_for_stoploss(
                        api_key, api_secret, symbol,
                        entry_price, stoploss_price,
                        initial_quantity, state
                    )

                    # สร้าง entry order
                    entry_order = None
                    if should_market_entry:
                        message(symbol, f"ราคาต่างจากจุด trigger {price_diff_percent:.2f}% - เข้าด้วย MARKET", "yellow")
                        entry_order = await create_order(
                            api_key, api_secret,
                            symbol=symbol,
                            side=entry_side,
                            price='now',
                            quantity=str(adjusted_quantity),
                            order_type='MARKET',
                            martingale_multiplier=state.martingale_multiplier
                        )
                    elif price_condition_met:
                        # เข้าด้วย LIMIT order เมื่อราคาอยู่ในช่วงที่เหมาะสม
                        limit_price = entry_trigger_price
                        message(symbol, f"ราคาอยู่ในช่วงเหมาะสม - ตั้ง LIMIT ที่ {limit_price:.8f}", "yellow")
                        entry_order = await create_order(
                            api_key, api_secret,
                            symbol=symbol,
                            side=entry_side,
                            price=str(limit_price),
                            quantity=str(adjusted_quantity),
                            order_type='LIMIT',
                            martingale_multiplier=state.martingale_multiplier
                        )
                    else:
                        message(symbol, f"ตั้ง STOP_MARKET ที่ {entry_trigger_price:.8f}", "yellow")
                        entry_order = await create_order(
                            api_key, api_secret,
                            symbol=symbol,
                            side=entry_side,
                            price=str(entry_trigger_price),
                            quantity=str(adjusted_quantity),
                            order_type='STOP_MARKET',
                            martingale_multiplier=state.martingale_multiplier
                        )

                    if entry_order:
                        # สร้าง Stoploss Order
                        stoploss_order = await create_order(
                            api_key, api_secret,
                            symbol=symbol,
                            side=stoploss_side,
                            price=str(stoploss_price),
                            quantity='MAX',
                            order_type='STOPLOSS_MARKET',
                            martingale_multiplier=state.martingale_multiplier
                        )

                        if stoploss_order:
                            if should_market_entry:
                                message(symbol, f"เข้า {entry_side.upper()} ใหม่ด้วย MARKET ORDER สำเร็จ", "green")
                                
                                # อัพเดทสถานะสำหรับ market entry
                                state.is_in_position = True
                                state.global_position_data.update({
                                    'entry_price': float(entry_order['average']),
                                    'entry_time': datetime.now(pytz.UTC),
                                    'position_side': entry_side,
                                })
                                state.entry_candle = await get_current_candle(api_key, api_secret, symbol, state.config.timeframe)
                                
                                # สร้าง Take Profit Orders
                                await setup_take_profit_orders(
                                    api_key, api_secret, symbol,
                                    state.global_position_data['entry_price'],
                                    state.global_position_data['position_side'],
                                    state.config.timeframe,
                                    state
                                )
                                
                                # รีเซ็ตข้อมูล entry orders
                                state.entry_orders = None
                                state.entry_side = None
                                state.entry_price = None
                                state.entry_stoploss_price = None
                                
                            else:
                                # อัพเดทสถานะสำหรับ pending entry (ทั้ง limit และ stop)
                                state.entry_side = entry_side
                                state.entry_price = entry_trigger_price
                                state.entry_stoploss_price = stoploss_price
                                state.entry_orders = {
                                    'entry_order': entry_order,
                                    'stoploss_order': stoploss_order,
                                    'is_market_entry': False,
                                    'is_limit_order': entry_order.get('type', '').lower() == 'limit'
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
                finally:
                    state.reset_position_data()
            else:
                state.reset_position_data()
                state.save_state()
        else:
            # รีเซ็ตสถานะ position ทั้งหมด
            state.reset_position_data()
            state.save_state()
            
    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"Error in position close handling: {str(e)}", "red")
        message(symbol, f"Error: {error_traceback}", "red")

async def _handle_new_candle(api_key, api_secret, symbol, state, current_candle_time,
                         position_side, ohlcv, rsi_cross):
    """จัดการแท่งเทียนใหม่"""
    try:
        state.last_candle_time = current_candle_time

        # จัดการ stoploss
        if state.is_in_position and state.last_candle_cross:
            await _adjust_stoploss_for_new_candle(
                api_key, api_secret, symbol, state, position_side)

        # อัพเดท Take Profit เมื่อมีแท่งเทียนใหม่
        if state.is_in_position and not state.is_swapping:
            await adjust_take_profit_orders(api_key, api_secret, symbol, state)

        # จัดการ is_wait_candle
        if state.is_wait_candle and position_side is not None:
            state.is_wait_candle = False
            if state.last_candle_cross and 'candle' in state.last_candle_cross:
                state.last_focus_price = (
                    min(state.last_candle_cross['candle'].get('low', 0), ohlcv[0][3])
                    if position_side == 'buy' else
                    max(state.last_candle_cross['candle'].get('high', 0), ohlcv[0][2])
                )
                state.last_focus_stopprice = (
                    max(state.last_candle_cross['candle'].get('high', 0), ohlcv[0][2])
                    if position_side == 'buy' else
                    min(state.last_candle_cross['candle'].get('low', 0), ohlcv[0][3])
                )
                message(symbol, 'ปิดแท่งเทียนหลังเจอสัญญาณตรงกันข้าม! รอดูว่าจะสลับ position หรือขยับ Stoploss', "yellow")

        # จัดการสัญญาณ RSI
        if rsi_cross and 'status' in rsi_cross and rsi_cross['status']:
            await _handle_rsi_signals(
                api_key, api_secret, symbol, state, position_side, rsi_cross, ohlcv[0] if ohlcv else None
            )

    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"Error in new candle handling: {str(e)}", "red")
        message(symbol, f"Error: {error_traceback}", "red")

async def _handle_stoploss_adjustment(api_key, api_secret, symbol, state, position_side, price):
    """จัดการการปรับ stoploss"""
    try:
        if position_side == 'buy':
            if price > state.last_focus_price * PRICE_INCREASE:
                # หาแท่งเทียนที่เกิดการทะลุ
                current_candle = state.current_candle
                focus_candle = state.last_candle_cross['candle']
                
                # เปรียบเทียบ low ของทั้งสองแท่ง
                focus_low = float(focus_candle['low'])
                current_low = float(current_candle['low'])
                
                # เลือก stoploss ที่เหมาะสม
                if focus_low < current_low:
                    new_stoploss = focus_low * PRICE_DECREASE
                    message(symbol, f"ใช้ low ของ focus candle เป็น stoploss", "cyan")
                else:
                    new_stoploss = current_low * PRICE_DECREASE
                    message(symbol, f"ใช้ low ของแท่งปัจจุบันเป็น stoploss", "cyan")
                    
                await change_stoploss_to_price(api_key, api_secret, symbol, new_stoploss)
                message(symbol, f"ปรับ Stop Loss เป็น {new_stoploss:.8f}", "cyan")
                state.is_wait_candle = False
                state.current_stoploss = new_stoploss
                
        elif position_side == 'sell':
            if price < state.last_focus_price * PRICE_DECREASE:
                # หาแท่งเทียนที่เกิดการทะลุ
                current_candle = state.current_candle
                focus_candle = state.last_candle_cross['candle']
                
                # เปรียบเทียบ high ของทั้งสองแท่ง
                focus_high = float(focus_candle['high'])
                current_high = float(current_candle['high'])
                
                # เลือก stoploss ที่เหมาะสม
                if focus_high > current_high:
                    new_stoploss = focus_high * PRICE_INCREASE
                    message(symbol, f"ใช้ high ของ focus candle เป็น stoploss", "cyan")
                else:
                    new_stoploss = current_high * PRICE_INCREASE
                    message(symbol, f"ใช้ high ของแท่งปัจจุบันเป็น stoploss", "cyan")
                    
                await change_stoploss_to_price(api_key, api_secret, symbol, new_stoploss)
                message(symbol, f"ปรับ Stop Loss เป็น {new_stoploss:.8f}", "cyan")
                state.is_wait_candle = False
                state.current_stoploss = new_stoploss
                
    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"Error in stoploss adjustment: {str(e)}", "red")
        message(symbol, f"Error: {error_traceback}", "red")

async def _adjust_stoploss_for_new_candle(api_key, api_secret, symbol, state, position_side):
    """ปรับ stoploss สำหรับแท่งเทียนใหม่"""
    try:
        current_candle = state.current_candle
        
        if current_candle and position_side:
            await adjust_stoploss(
                api_key, api_secret, symbol, state,
                position_side, state.entry_candle['timestamp'],
                state.current_stoploss
            )
        else:
            if not current_candle:
                message(symbol, "ไม่สามารถดึงข้อมูลแท่งเทียนปัจจุบัน ข้ามการปรับ Stoploss", "yellow")
            if not position_side:
                message(symbol, "ไม่สามารถดึงข้อมูลด้านของ position ข้ามการปรับ Stoploss", "yellow")

    except Exception as e:
        message(symbol, f"Error in stoploss adjustment for new candle: {str(e)}", "red")

async def setup_take_profit_orders(api_key, api_secret, symbol, entry_price, position_side, timeframe, state):
    """สร้าง take profit orders โดยใช้การตั้งค่าจาก config"""
    try:
        if entry_price is None:
            message(symbol, "ไม่มีข้อมูล entry price สำหรับคำนวณ Take Profit", "red")
            return []

        # ดึง ATR - แก้ไขลำดับการส่งพารามิเตอร์
        atr = state.current_atr_length_2
        if atr is None:
            message(symbol, "ไม่สามารถคำนวณค่า ATR ได้", "red")
            return []
            
        atr_percent = (atr / entry_price) * 100
        message(symbol, f"คำนวณ TP จาก: Entry: {entry_price}, ATR: {atr:.8f} ({atr_percent:.2f}%)", "blue")

        # ดึงการตั้งค่า TP จาก config
        tp_config = state.config.take_profits
        if not tp_config or not tp_config.get('levels'):
            message(symbol, "ไม่พบการตั้งค่า Take Profit ใน config", "yellow")
            return []

        # เตรียมคำสั่ง TP
        orders = []
        
        for level in tp_config['levels']:
            level_id = level['id']
            target_atr = level['target_atr']
            size = level['size']

            # คำนวณราคา TP
            if position_side == 'buy':
                tp_base = entry_price + (atr * target_atr)
                tp_price = tp_base * (PRICE_INCREASE + (PRICE_CHANGE_THRESHOLD * (target_atr * 2)))
            else:
                tp_base = entry_price - (atr * target_atr)
                tp_price = tp_base * (PRICE_DECREASE - (PRICE_CHANGE_THRESHOLD * (target_atr * 2)))

            # ปรับราคาตามข้อจำกัดของ exchange
            adjusted_price = await get_adjusted_price(
                api_key, api_secret, str(tp_price), entry_price, position_side, symbol
            )

            if adjusted_price is None:
                message(symbol, f"ไม่สามารถปรับราคา {level_id} ได้", "red")
                continue

            # คำนวณกำไรเป็นเปอร์เซ็นต์
            profit_percent = abs((adjusted_price - entry_price) / entry_price * 100)
            distance_in_atr = abs(adjusted_price - entry_price) / atr
            message(symbol, 
                f"{level_id}: {adjusted_price:.8f} ({profit_percent:.2f}%, " +
                f"{distance_in_atr:.1f} ATR, Size: {size})", "blue"
            )

            # สร้างคำสั่ง TP
            side = 'sell' if position_side == 'buy' else 'buy'
            tp_order = await create_order(
                api_key, api_secret,
                symbol=symbol,
                side=side,
                price=str(adjusted_price),
                quantity=size,
                order_type='TAKE_PROFIT_MARKET',
                martingale_multiplier=state.martingale_multiplier
            )

            if tp_order:
                orders.append(tp_order)
                message(symbol, f"ตั้ง {level_id} ({size}) ที่ราคา {adjusted_price:.8f}", "cyan")
            else:
                message(symbol, f"ไม่สามารถสร้างคำสั่ง {level_id} ได้", "red")

        return orders

    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"เกิดข้อผิดพลาดในการสร้าง Take Profit Orders: {str(e)}", "red")
        message(symbol, f"Error: {error_traceback}", "red")
        return []

async def _handle_entry_orders(api_key, api_secret, symbol, state, price, exchange):
    """จัดการ entry orders"""
    try:
        # 1. ตรวจสอบว่ามี state entry_orders หรือไม่
        if not state.entry_orders:
            return

        # 2. เช็คสถานะ position
        has_position = await check_position(api_key, api_secret, symbol)
        
        # 3. ถ้า state บอกว่าไม่มี position แต่จริงๆ มี แสดงว่า order ทำงานแล้ว
        if not state.is_in_position and has_position:
            await _handle_position_entered(api_key, api_secret, symbol, state, exchange)
            return

        # 6. ตรวจสอบเงื่อนไขการยกเลิก orders
        current_candle = state.current_candle
        if not current_candle:
            return
            
        
        current_low = float(current_candle['low'])
        current_high = float(current_candle['high'])
        
        # Debug log
        """message(symbol, f"ตรวจสอบเงื่อนไขยกเลิก Orders สำหรับแท่งใหม่:", "yellow")
        message(symbol, f"Entry Side: {state.entry_side}", "yellow")
        message(symbol, f"Stoploss Price: {state.entry_stoploss_price}", "yellow")
        message(symbol, f"Current High: {current_high}", "yellow")
        message(symbol, f"Current Low: {current_low}", "yellow")"""
        
        should_cancel = False
        reason = ""
        
        # เช็คเงื่อนไขการยกเลิก
        if state.entry_side == 'buy' and current_low <= state.entry_stoploss_price:
            should_cancel = True
            reason = f"ราคาต่ำสุดของแท่ง ({current_low:.8f}) ต่ำกว่าหรือเท่ากับ stoploss ({state.entry_stoploss_price:.8f})"
        elif state.entry_side == 'sell' and current_high >= state.entry_stoploss_price:
            should_cancel = True
            reason = f"ราคาสูงสุดของแท่ง ({current_high:.8f}) สูงกว่าหรือเท่ากับ stoploss ({state.entry_stoploss_price:.8f})"
        
        if should_cancel:
            message(symbol, f"ยกเลิก Orders เนื่องจาก: {reason}", "yellow")
            await clear_all_orders(api_key, api_secret, symbol)
            state.reset_order_state()
            state.save_state()

    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"เกิดข้อผิดพลาดในการจัดการ Entry Orders: {str(e)}", "red")
        message(symbol, f"Error Traceback: {error_traceback}", "red")

async def _handle_position_entered(api_key, api_secret, symbol, state, exchange):
    """จัดการกรณี position ถูกเปิดแล้ว"""
    message(symbol, f"Entry order ทำงานแล้ว กำลังอัพเดทสถานะ", "green")
    
    # อัพเดทสถานะ position
    state.reset_position_data()
    state.is_in_position = True
    
    try:
        positions = await exchange.fetch_positions([symbol])
        current_position = next((pos for pos in positions if float(pos['contracts']) != 0), None)
        
        if current_position:
            state.global_position_data.update({
                'entry_price': float(current_position['entryPrice']),
                'entry_time': datetime.now(pytz.UTC),
                'position_side': 'buy' if current_position['side'] == 'long' else 'sell',
                'position_size': float(current_position['contracts']),
                'leverage': int(current_position['leverage']),
                'margin_type': current_position['marginType']
            })
            
            state.entry_candle = state.current_candle
            
            # สร้าง Take Profit Orders
            await setup_take_profit_orders(
                api_key, api_secret, symbol,
                state.global_position_data['entry_price'],
                state.global_position_data['position_side'],
                state.config.timeframe,
                state
            )
            
            state.reset_order_state()
            
        else:
            message(symbol, "ไม่พบข้อมูล position", "red")
            
    except Exception as e:
        message(symbol, f"เกิดข้อผิดพลาดในการดึงข้อมูล position: {str(e)}", "red")
    
    state.save_state()

async def manage_position_profit(api_key: str, api_secret: str, symbol: str, state: SymbolState):
    """จัดการ position profit รวมถึงการย้าย stoploss ตามระดับ TP ต่างๆ"""
    exchange = None
    try:
        if not state.is_in_position:
            return

        exchange = await create_future_exchange(api_key, api_secret)

        current_stoploss = state.current_stoploss
        atr = state.current_atr_tp
        current_candle = state.current_candle

        if current_candle is None or current_stoploss is None or atr is None:
            message(symbol, "ไม่มีข้อมูลที่จำเป็นสำหรับการจัดการกำไร", "yellow")
            return

        entry_price = state.global_position_data['entry_price']
        position_side = state.global_position_data['position_side']

        max_price = float(current_candle['high'])
        min_price = float(current_candle['low'])

        # ดึงการตั้งค่า TP จาก config
        tp_config = state.config.take_profits
        if not tp_config:
            return

        # เรียงลำดับ TP levels ตาม target_atr จากน้อยไปมาก
        tp_levels = sorted(tp_config['levels'], key=lambda x: x['target_atr'])
        
        # สร้าง dictionary เพื่อเก็บราคา TP แต่ละระดับ
        tp_prices = {}
        prev_tp_price = entry_price  # เริ่มต้นด้วยราคา entry

        for level in tp_levels:
            level_id = level['id']
            target_atr = level['target_atr']

            # คำนวณราคา TP
            if position_side == 'buy':
                tp_base = entry_price + (atr * target_atr)
                tp_price = tp_base * (PRICE_INCREASE + (PRICE_CHANGE_THRESHOLD * (target_atr * 2)))
            else:
                tp_base = entry_price - (atr * target_atr)
                tp_price = tp_base * (PRICE_DECREASE - (PRICE_CHANGE_THRESHOLD * (target_atr * 2)))

            tp_prices[level_id] = tp_price

            # ตรวจสอบว่าถึง TP หรือไม่
            price_reached_tp = False
            if position_side == 'buy':
                price_reached_tp = max_price >= tp_price
            else:
                price_reached_tp = min_price <= tp_price

            if price_reached_tp and not state.tp_levels_hit[level_id]:
                message(symbol, f"ราคาถึงระดับ {level_id}", "cyan")
                state.tp_levels_hit[level_id] = True

                # ตรวจสอบการย้าย stoploss
                if level.get('move_sl_to_prev_level', False):
                    try:
                        # กำหนดราคา stoploss ใหม่
                        new_stoploss = None
                        
                        if prev_tp_price == entry_price:
                            # ถ้าเป็น TP แรก ใช้ราคา entry
                            if position_side == 'buy':
                                new_stoploss = entry_price * (PRICE_DECREASE - PRICE_CHANGE_THRESHOLD)
                            else:
                                new_stoploss = entry_price * (PRICE_INCREASE + PRICE_CHANGE_THRESHOLD)
                            message(symbol, f"ย้าย stoploss ไปที่จุดเข้า {new_stoploss:.8f}", "cyan")
                        else:
                            # ถ้าเป็น TP ถัดไป ใช้ราคา TP ก่อนหน้า
                            new_stoploss = prev_tp_price
                            message(symbol, f"ย้าย stoploss ไปที่ TP ก่อนหน้า {new_stoploss:.8f}", "cyan")

                        if new_stoploss is not None:
                            if ((position_side == 'buy' and current_stoploss < new_stoploss) or
                                (position_side == 'sell' and current_stoploss > new_stoploss)):
                                await change_stoploss_to_price(api_key, api_secret, symbol, new_stoploss)
                                state.current_stoploss = new_stoploss
                                message(symbol, "ปรับ stoploss เรียบร้อย", "cyan")

                    except Exception as e:
                        message(symbol, f"เกิดข้อผิดพลาดในการปรับ stoploss: {str(e)}", "red")

            # อัพเดทราคา TP ก่อนหน้า
            prev_tp_price = tp_price

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

async def should_adjust_tp(state: SymbolState) -> bool:
    """ตรวจสอบว่าควรปรับ TP หรือไม่"""
    try:
        # เช็คการเปิดใช้งาน dynamic TP
        if not state.config.take_profits.get('use_dynamic_tp', True):
            return False
            
        if not state.entry_candle or not state.current_candle:
            return False
            
        # นับจำนวนแท่งหลัง entry
        entry_time = state.entry_candle['timestamp']
        current_time = state.current_candle['timestamp']
        
        candles = await fetch_ohlcv(state.symbol, state.config.timeframe, limit=10)
        if not candles:
            return False
            
        # หาจำนวนแท่งที่ปิดไปแล้วหลัง entry
        closed_candles = 0
        for candle in candles:
            if candle[0] > entry_time and candle[0] < current_time:
                closed_candles += 1
                
        return closed_candles >= 2
        
    except Exception as e:
        message(state.symbol, f"Error checking TP adjustment: {str(e)}", "red")
        return False

async def get_tp_reference_price(state: SymbolState, position_side: str) -> tuple:
    """หาราคาอ้างอิงสำหรับคำนวณ TP และ ATR โดยใช้ percentage weight"""
    try:
        # ดึงข้อมูล 3 แท่งล่าสุดที่ปิดแล้ว
        candles = await fetch_ohlcv(state.symbol, state.config.timeframe, limit=4)
        if len(candles) < 4:  # รวมแท่งปัจจุบันด้วย
            return None, None
            
        # ใช้แท่งที่ 3 นับจากปัจจุบัน (index = -4)
        reference_candle = candles[-4]
        entry_price = state.global_position_data['entry_price']
        
        # ดึงค่า weight percentage จาก config
        weight_percent = state.config.take_profits.get('average_with_entry', 50)
        # แปลงเป็นทศนิยม (0-1)
        weight = weight_percent / 100.0
        
        if position_side == 'buy':
            # ใช้ high ถ้าเป็น long position
            candle_price = float(reference_candle[2])
            
            # คำนวณราคาอ้างอิงตาม weight
            if weight == 0:  # ใช้ entry price อย่างเดียว
                reference_price = entry_price
            elif weight == 1:  # ใช้ราคา candle อย่างเดียว
                reference_price = candle_price
            else:
                # คำนวณราคาตาม weight
                # ใช้ entry price * (1-weight) + candle price * weight
                reference_price = (entry_price * (1 - weight)) + (candle_price * weight)
                
        else:  # position_side == 'sell'
            # ใช้ low ถ้าเป็น short position
            candle_price = float(reference_candle[3])
            
            # คำนวณราคาอ้างอิงตาม weight
            if weight == 0:  # ใช้ entry price อย่างเดียว
                reference_price = entry_price
            elif weight == 1:  # ใช้ราคา candle อย่างเดียว
                reference_price = candle_price
            else:
                # คำนวณราคาตาม weight
                # ใช้ entry price * (1-weight) + candle price * weight
                reference_price = (entry_price * (1 - weight)) + (candle_price * weight)
            
        return reference_price, reference_candle

    except Exception as e:
        message(state.symbol, f"Error getting TP reference price: {str(e)}", "red")
        return None, None

async def adjust_take_profit_orders(api_key: str, api_secret: str, symbol: str, state: SymbolState):
    """ปรับปรุง take profit orders ตามสภาพตลาด โดยใช้ ATR 7"""
    try:
        if not state.is_in_position:
            return
            
        # ตรวจสอบว่าควรปรับ TP หรือไม่
        if not await should_adjust_tp(state):
            return
            
        position_side = state.global_position_data['position_side']
        
        # หาราคาอ้างอิงและแท่งเทียนสำหรับคำนวณ
        reference_price, reference_candle = await get_tp_reference_price(state, position_side)
        if not reference_price or not reference_candle:
            return
            
        # ใช้ ATR period 7 สำหรับ dynamic TP
        atr = state.current_atr_tp  # ATR period 7
        if not atr:
            message(symbol, "ไม่สามารถคำนวณค่า ATR(7) ได้สำหรับ dynamic TP", "red")
            return
            
        message(symbol, f"ปรับ TP ใหม่ จากราคา {reference_price:.8f} (ATR7: {atr:.8f})", "cyan")
        
        # ลบ TP orders เก่า
        await clear_tp_orders(api_key, api_secret, symbol)
        
        # สร้าง TP ใหม่โดยใช้ ATR 7
        tp_orders = await create_dynamic_tp_orders(
            api_key, api_secret, symbol,
            reference_price, position_side,
            state.config.timeframe, state,
            atr=atr  # ส่ง ATR 7 ไปใช้งาน
        )
        
        if tp_orders:
            message(symbol, f"สร้าง TP ใหม่สำเร็จ {len(tp_orders)} orders", "green")
            
    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"Error adjusting TP orders: {str(e)}", "red")
        message(symbol, f"Error: {error_traceback}", "red")

async def create_dynamic_tp_orders(api_key, api_secret, symbol, reference_price, position_side, timeframe, state, atr=None):
    """สร้าง take profit orders แบบไดนามิก โดยใช้ ATR 7"""
    try:
        # ใช้ ATR 7 ที่ส่งมา หรือดึงจาก state ถ้าไม่ได้ส่งมา
        if not atr:
            atr = state.current_atr_tp
            if not atr:
                message(symbol, "ไม่สามารถคำนวณค่า ATR(7) ได้", "red")
                return []

        atr_percent = (atr / reference_price) * 100
        message(symbol, f"คำนวณ TP จาก: Price: {reference_price:.8f}, ATR(7): {atr:.8f} ({atr_percent:.2f}%)", "blue")

        # ดึงการตั้งค่า TP จาก config
        tp_config = state.config.take_profits
        if not tp_config or not tp_config.get('levels'):
            message(symbol, "ไม่พบการตั้งค่า Take Profit ใน config", "yellow")
            return []

        # สร้างคำสั่ง TP
        orders = []
        previous_tp_price = reference_price  # เริ่มต้นที่ราคา reference

        for level in tp_config['levels']:
            level_id = level['id']
            if state.tp_levels_hit.get(level_id, False):
                message(symbol, f"ข้าม {level_id} เนื่องจากทำสำเร็จแล้ว", "blue")
                continue

            target_atr = level['target_atr']
            size = level['size']

            # คำนวณราคา TP โดยใช้ ATR 7
            if position_side == 'buy':
                tp_price = reference_price + (atr * target_atr)
                
                # ป้องกันไม่ให้TP ถอยหลัง
                if tp_price <= previous_tp_price:
                    tp_price = (previous_tp_price + tp_price) / 2
            else:
                tp_price = reference_price - (atr * target_atr)
                
                # ป้องกันไม่ให้TP ถอยหลัง
                if tp_price >= previous_tp_price:
                    tp_price = (previous_tp_price + tp_price) / 2

            # ปรับราคาตามข้อจำกัดของ exchange
            adjusted_price = await get_adjusted_price(
                api_key, api_secret,
                str(tp_price),
                reference_price,
                position_side,
                symbol
            )

            if adjusted_price is None:
                message(symbol, f"ไม่สามารถปรับราคา {level_id} ได้", "red")
                continue

            # อัพเดท previous_tp_price
            previous_tp_price = adjusted_price

            # คำนวณกำไรเป็นเปอร์เซ็นต์
            profit_percent = abs((adjusted_price - reference_price) / reference_price * 100)
            distance_in_atr = abs(adjusted_price - reference_price) / atr
            
            message(symbol, 
                f"{level_id}: {adjusted_price:.8f} " +
                f"({profit_percent:.2f}%, {distance_in_atr:.1f} ATR7, Size: {size})",
                "blue"
            )

            # สร้างคำสั่ง TP
            side = 'sell' if position_side == 'buy' else 'buy'
            tp_order = await create_order(
                api_key, api_secret,
                symbol=symbol,
                side=side,
                price=str(adjusted_price),
                quantity=size,
                order_type='TAKE_PROFIT_MARKET'
            )

            if tp_order:
                orders.append(tp_order)
                message(symbol, f"ตั้ง {level_id} ({size}) ที่ราคา {adjusted_price:.8f}", "cyan")
            else:
                message(symbol, f"ไม่สามารถสร้างคำสั่ง {level_id} ได้", "red")

        return orders

    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"เกิดข้อผิดพลาดในการสร้าง Dynamic Take Profit Orders: {str(e)}", "red")
        message(symbol, f"Error: {error_traceback}", "red")
        return []

        
async def record_trade(api_key, api_secret, symbol, action, entry_price, exit_price, amount, reason, state):
    """บันทึกข้อมูลการเทรด"""
    try:
        exchange = await create_future_exchange(api_key, api_secret)
        
        try:
            # โหลดประวัติการเทรดที่มีอยู่
            trades = []
            try:
                with open(state.trade_record_file, 'r') as f:
                    trades = json.load(f)
            except FileNotFoundError:
                pass

            # ดึงข้อมูล position จาก state
            position_info = state.global_position_data
            actual_entry_price = float(entry_price)
            actual_exit_price = float(exit_price)
            
            # คำนวณ quantity ที่แท้จริง
            if position_info['position_size']:
                actual_amount = abs(float(position_info['position_size']))
            else:
                adjusted_amount = await get_adjusted_quantity(api_key, api_secret, amount, actual_entry_price, symbol)
                actual_amount = adjusted_amount if adjusted_amount is not None else 0

            # Calculate actual profit/loss
            if action in ['BUY', 'SELL']:
                profit_loss = ((actual_exit_price - actual_entry_price) if action == 'BUY' else 
                            (actual_entry_price - actual_exit_price)) * actual_amount
            else:  # action == 'SWAP'
                profit_loss = (actual_exit_price - actual_entry_price) * actual_amount

            # Martingale Logic
            if state.config.martingale_enabled:
                if profit_loss < -1:  # Loss greater than $1
                    state.consecutive_losses += 1
                    
                    # Calculate multiplier with configurable max and step
                    state.martingale_multiplier = min(
                        1.0 + (state.config.martingale_step * min(state.consecutive_losses, 4)), 
                        state.config.martingale_max_multiplier
                    )
                    
                    message(symbol, 
                        f"Martingale: Consecutive Loss {state.consecutive_losses}, " +
                        f"Multiplier increased to {state.martingale_multiplier}", "red"
                    )
                else:  # Profitable trade
                    # Reset Martingale state based on config
                    if state.config.martingale_reset_on_win:
                        state.martingale_multiplier = 1.0
                        state.consecutive_losses = 0
                        
                        message(symbol, 
                            f"Martingale: Trade profitable, resetting multiplier", "green"
                        )

            # Adjust entry amount based on multiplier
            adjusted_entry_amount = state.config.entry_amount.replace('$', '')
            adjusted_entry_amount = f"${float(adjusted_entry_amount) * state.martingale_multiplier}"

            # Update trade record with Martingale details
            trade['martingale_details'] = {
                'enabled': state.config.martingale_enabled,
                'multiplier': state.martingale_multiplier,
                'consecutive_losses': state.consecutive_losses,
                'original_entry_amount': state.config.entry_amount,
                'adjusted_entry_amount': adjusted_entry_amount
            }

            # คำนวณเปอร์เซ็นต์กำไร/ขาดทุน
            profit_loss_percentage = (profit_loss / (actual_entry_price * actual_amount)) * 100

            # สร้างบันทึกการเทรด
            trade = {
                'timestamp': datetime.now().isoformat(),
                'symbol': symbol,
                'action': action,
                'entry_price': actual_entry_price,
                'exit_price': actual_exit_price,
                'amount': actual_amount,
                'profit_loss': float(profit_loss),
                'profit_loss_percentage': float(profit_loss_percentage),
                'reason': reason,
                'leverage': position_info.get('leverage', 20),
                'margin_type': position_info.get('margin_type', 'cross'),
                'position_size_usd': float(actual_amount * actual_entry_price)
            }

            # บันทึกข้อมูล
            trades.append(trade)
            os.makedirs(os.path.dirname(state.trade_record_file), exist_ok=True)
            with open(state.trade_record_file, 'w') as f:
                json.dump(trades, f, indent=2)

            # อัพเดท performance metrics
            state.performance_data['trades_count'] += 1
            if profit_loss > 0:
                state.performance_data['winning_trades'] += 1
            else:
                state.performance_data['losing_trades'] += 1
            
            state.performance_data['total_profit'] += profit_loss
            state.performance_data['largest_profit'] = max(state.performance_data['largest_profit'], profit_loss)
            state.performance_data['largest_loss'] = min(state.performance_data['largest_loss'], profit_loss)

            # แสดงผลลัพธ์
            message(symbol, f"บันทึกการเทรด: {action} {symbol}", "cyan")
            message(symbol, f"Entry: {actual_entry_price:.2f} | Exit: {actual_exit_price:.2f}", "cyan")
            message(symbol, f"จำนวน: {actual_amount:.8f} ({actual_amount * actual_entry_price:.2f} USD)", "cyan")
            message(symbol, f"Leverage: {position_info.get('leverage', 20)}x | Margin Type: {position_info.get('margin_type', 'cross')}", "cyan")
            message(symbol, f"กำไร/ขาดทุน: {profit_loss:.2f} USDT ({profit_loss_percentage:.2f}%)", "cyan")
            
        except Exception as e:
            error_traceback = traceback.format_exc()
            message(symbol, f"เกิดข้อผิดพลาดในการบันทึกการเทรด: {str(e)}", "red")
            message(symbol, f"Error: {error_traceback}", "red")
            
    finally:
        if exchange:
            await exchange.close()

async def get_current_stoploss(api_key, api_secret, symbol, state):
    """ดึงค่า stoploss ปัจจุบัน"""
    exchange = None
    try:
        exchange = await create_future_exchange(api_key, api_secret)
        exchange_symbol = symbol.replace("USDT", "/USDT:USDT") if 'USDT' in symbol and '/USDT:USDT' not in symbol else symbol
        
        # ดึงรายการ orders และ position
        orders = await exchange.fetch_open_orders(symbol)
        positions = await exchange.fetch_positions([symbol])
        
        # หา position ปัจจุบัน
        current_position = None
        for position in positions:
            if (position['symbol'] == symbol or position['symbol'] == exchange_symbol) and float(position['contracts']) != 0:
                current_position = position
                break
                
        if not current_position:
            return None
            
        # หา stop order ที่ตรงกับ side ปัจจุบัน
        current_side = current_position['side']
        
        for order in orders:
            if (order['type'] == 'stop_market' and 
                ((current_side == 'long' and order['side'] == 'sell') or 
                 (current_side == 'short' and order['side'] == 'buy'))):
                
                stop_price = None
                if 'params' in order and 'stopPrice' in order['params']:
                    stop_price = order['params']['stopPrice']
                elif 'info' in order and 'stopPrice' in order['info']:
                    stop_price = order['info']['stopPrice']
                
                if stop_price is not None:
                    return float(stop_price)
        
        return state.current_stoploss

    except Exception as e:
        return state.current_stoploss
    finally:
        if exchange:
            await exchange.close()

async def adjust_stoploss(api_key, api_secret, symbol, state, position_side, cross_timestamp, current_stoploss=None):
    """ปรับ stoploss โดยใช้ค่า PRICE_DECREASE และ PRICE_INCREASE"""
    exchange = None
    try:
        if not state.entry_candle:
            message(symbol, "ไม่พบข้อมูล entry candle ข้ามการปรับ stoploss", "yellow")
            return None
            
        exchange = await create_future_exchange(api_key, api_secret)
        
        # ใช้ข้อมูลจาก state ถ้ามี
        ohlcv = await fetch_ohlcv(symbol, state.config.timeframe, limit=6)

        if not ohlcv or len(ohlcv) < 6:
            message(symbol, "ข้อมูล OHLCV ไม่เพียงพอ ข้ามการปรับ stoploss", "yellow")
            return None
        
        closed_candles = ohlcv[:-1]
        entry_timestamp = state.entry_candle['timestamp']
        filtered_candles = [candle for candle in closed_candles if candle[0] >= entry_timestamp]
        
        if len(filtered_candles) < 3:
            message(symbol, f"มีแท่งเทียนหลัง entry ไม่พอ ({len(filtered_candles)}/3)", "yellow")
            return None
        
        # คำนวณราคาสำหรับแต่ละแท่ง
        if position_side == 'buy':
            prices = [candle[3] * PRICE_DECREASE for candle in filtered_candles]
        elif position_side == 'sell':
            prices = [candle[2] * PRICE_INCREASE for candle in filtered_candles]
        else:
            raise ValueError("ทิศทาง position ไม่ถูกต้อง")

        # ค้นหาชุด 3 แท่งที่เข้าเงื่อนไข
        valid_sequences = []
        for i in range(len(prices)-1, 1, -1):
            for j in range(i-1, 0, -1):
                for k in range(j-1, -1, -1):
                    if position_side == 'buy':
                        if prices[i] > prices[j] > prices[k]:
                            valid_sequences.append((k, j, i))
                    else:
                        if prices[i] < prices[j] < prices[k]:
                            valid_sequences.append((k, j, i))

        if not valid_sequences:
            #message(symbol, "ไม่พบชุดแท่งเทียนที่เข้าเงื่อนไข", "yellow")
            return None

        best_sequence = valid_sequences[0]
        new_stoploss = prices[best_sequence[0]]

        # ตรวจสอบเงื่อนไขการปรับ stoploss
        if current_stoploss is not None:
            if ((position_side == 'buy' and new_stoploss <= current_stoploss) or
                (position_side == 'sell' and new_stoploss >= current_stoploss) or
                new_stoploss == current_stoploss):
                return None

        # ปรับหรือสร้าง stoploss
        await change_stoploss_to_price(api_key, api_secret, symbol, new_stoploss)
        sequence_prices = [prices[i] for i in best_sequence]
        sequence_str = ', '.join([f"{price:.2f}" for price in sequence_prices])

        if current_stoploss is None:
            message(symbol, f"สร้าง stoploss ที่ราคา {new_stoploss:.2f}", "cyan")
        else:
            message(symbol, f"ปรับ stoploss จาก {current_stoploss:.2f} เป็น {new_stoploss:.2f}", "cyan")

        state.current_stoploss = new_stoploss
        return new_stoploss

    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"เกิดข้อผิดพลาดขณะปรับ stoploss: {str(e)}", "yellow")
        message(symbol, f"Error: {error_traceback}", "red")
        return None
    finally:
        if exchange:
            await exchange.close()

async def check_and_recreate_stoploss(api_key: str, api_secret: str, symbol: str, state: SymbolState):
    """ตรวจสอบและสร้าง stoploss ใหม่ถ้าไม่พบ"""
    try:
        if not state.is_in_position or not state.entry_candle:
            return

        # ตรวจสอบ stoploss orders จาก state.current_orders
        position_side = state.global_position_data['position_side']
        
        # ค้นหา stoploss order
        has_stoploss = False
        for order in state.current_orders:
            if (order['type'].lower() == 'stop_market' and 
                ((position_side == 'buy' and order['side'] == 'sell') or
                 (position_side == 'sell' and order['side'] == 'buy'))):
                has_stoploss = True
                break

        if not has_stoploss:
            message(symbol, "ไม่พบ Stoploss Order กำลังสร้างใหม่...", "yellow")
            
            # คำนวณราคา stoploss จาก entry_candle
            entry_candle = state.entry_candle
            if position_side == 'buy':
                stoploss_price = float(entry_candle['low']) * PRICE_DECREASE
            else:  # sell
                stoploss_price = float(entry_candle['high']) * PRICE_INCREASE

            # สร้าง stoploss order ใหม่
            stoploss_order = await create_order(
                api_key, api_secret,
                symbol=symbol,
                side='sell' if position_side == 'buy' else 'buy',
                price=str(stoploss_price),
                quantity='MAX',
                order_type='STOPLOSS_MARKET',
                martingale_multiplier=state.martingale_multiplier
            )

            if stoploss_order:
                message(symbol, f"สร้าง Stoploss Order ใหม่ที่ราคา {stoploss_price:.8f}", "green")
                state.current_stoploss = stoploss_price
            else:
                message(symbol, "ไม่สามารถสร้าง Stoploss Order ได้", "red")

    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"เกิดข้อผิดพลาดในการตรวจสอบ/สร้าง Stoploss: {str(e)}", "red")
        message(symbol, f"Error: {error_traceback}", "red")

async def setup_take_profit_orders(api_key, api_secret, symbol, entry_price, position_side, timeframe, state):
    """สร้าง take profit orders โดยใช้การตั้งค่าจาก config และ ATR 7"""
    try:
        if entry_price is None:
            message(symbol, "ไม่มีข้อมูล entry price สำหรับคำนวณ Take Profit", "red")
            return []

        # ใช้ ATR 7 สำหรับ TP
        atr = state.current_atr_tp
        if atr is None:
            message(symbol, "ไม่สามารถคำนวณค่า ATR(7) ได้", "red")
            return []
            
        atr_percent = (atr / entry_price) * 100
        message(symbol, f"คำนวณ TP จาก: Entry: {entry_price}, ATR(7): {atr:.8f} ({atr_percent:.2f}%)", "blue")

        # ดึงการตั้งค่า TP จาก config
        tp_config = state.config.take_profits
        if not tp_config or not tp_config.get('levels'):
            message(symbol, "ไม่พบการตั้งค่า Take Profit ใน config", "yellow")
            return []

        # เตรียมคำสั่ง TP
        orders = []
        
        for level in tp_config['levels']:
            level_id = level['id']
            target_atr = level['target_atr']
            size = level['size']

            # คำนวณราคา TP
            if position_side == 'buy':
                tp_base = entry_price + (atr * target_atr)
                tp_price = tp_base * (PRICE_INCREASE + (PRICE_CHANGE_THRESHOLD * (target_atr * 2)))
            else:
                tp_base = entry_price - (atr * target_atr)
                tp_price = tp_base * (PRICE_DECREASE - (PRICE_CHANGE_THRESHOLD * (target_atr * 2)))

            # ปรับราคาตามข้อจำกัดของ exchange
            adjusted_price = await get_adjusted_price(
                api_key, api_secret, str(tp_price), entry_price, position_side, symbol
            )

            if adjusted_price is None:
                message(symbol, f"ไม่สามารถปรับราคา {level_id} ได้", "red")
                continue

            # คำนวณกำไรเป็นเปอร์เซ็นต์
            profit_percent = abs((adjusted_price - entry_price) / entry_price * 100)
            distance_in_atr = abs(adjusted_price - entry_price) / atr
            message(symbol, 
                f"{level_id}: {adjusted_price:.8f} ({profit_percent:.2f}%, " +
                f"{distance_in_atr:.1f} ATR, Size: {size})", "blue"
            )

            # สร้างคำสั่ง TP
            side = 'sell' if position_side == 'buy' else 'buy'
            tp_order = await create_order(
                api_key, api_secret,
                symbol=symbol,
                side=side,
                price=str(adjusted_price),
                quantity=size,
                order_type='TAKE_PROFIT_MARKET',
                martingale_multiplier=state.martingale_multiplier
            )

            if tp_order:
                orders.append(tp_order)
                message(symbol, f"ตั้ง {level_id} ({size}) ที่ราคา {adjusted_price:.8f}", "cyan")
            else:
                message(symbol, f"ไม่สามารถสร้างคำสั่ง {level_id} ได้", "red")

        return orders

    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"เกิดข้อผิดพลาดในการสร้าง Take Profit Orders: {str(e)}", "red")
        message(symbol, f"Error: {error_traceback}", "red")
        return []
    
async def update_market_indicators(api_key: str, api_secret: str, symbol: str, state: SymbolState):
    """อัพเดทค่า ATR และ RSI Period เมื่อมีแท่งเทียนใหม่"""
    try:
        # ดึงข้อมูลแท่งเทียน
        rsi_config = state.config.rsi_period
        
        # เพิ่ม ATR period 7 สำหรับ TP
        max_length = max(rsi_config['atr']['length2'], rsi_config['atr']['length1'], 7)
        required_candles = int(max_length * 1.2)
        
        ohlcv = await fetch_ohlcv(symbol, state.config.timeframe, limit=required_candles)
        
        if not ohlcv or len(ohlcv) < max_length + 1:
            message(symbol, f"ข้อมูลไม่พอสำหรับคำนวณ ATR (มี {len(ohlcv)} แท่ง)", "yellow")
            return False

        # คำนวณ ATR สำหรับทุกช่วง
        def calculate_atr_value(length):
            tr_values = []
            for i in range(1, len(ohlcv)):
                high = ohlcv[i][2]
                low = ohlcv[i][3]
                prev_close = ohlcv[i-1][4]
                
                tr = max(
                    high - low,
                    abs(high - prev_close),
                    abs(low - prev_close)
                )
                tr_values.append(tr)

            alpha = 1.0 / length
            rma = tr_values[0]
            for tr in tr_values[1:]:
                rma = (alpha * tr) + ((1 - alpha) * rma)
            return rma

                # คำนวณ ATR ทั้งสามค่า
        atr_short = calculate_atr_value(rsi_config['atr']['length1'])
        atr_long = calculate_atr_value(rsi_config['atr']['length2'])
        
        # คำนวณ ATR สำหรับ TP แบบ dynamic
        atr_tp_period = calculate_atr_value(rsi_config['atr']['length_tp'])
        
        # คำนวณ weight จาก percent (0-100)
        weight = rsi_config['atr']['weight_percent'] / 100.0
        
        # คำนวณ ATR TP โดยใช้ weighted average
        atr_tp = (atr_tp_period * weight) + (atr_long * (1 - weight))
        
        # เก็บค่า ATR ล่าสุด
        state.current_atr_length_1 = atr_short
        state.current_atr_length_2 = atr_long
        state.current_atr_tp = atr_tp  # เก็บค่า ATR 7

        # คำนวณ RSI Period
        if rsi_config.get('use_dynamic_period', True):
            atr_diff_percent = ((atr_short - atr_long) / atr_long) * 100
            
            if atr_diff_percent >= rsi_config['atr']['max_percent']:
                current_rsi_period = rsi_config['rsi_period_max']
            elif atr_diff_percent <= rsi_config['atr']['min_percent']:
                current_rsi_period = rsi_config['rsi_period_min']
            else:
                period_range = rsi_config['rsi_period_max'] - rsi_config['rsi_period_min']
                volatility_range = rsi_config['atr']['max_percent'] - rsi_config['atr']['min_percent']
                period_step = (atr_diff_percent - rsi_config['atr']['min_percent']) / volatility_range
                current_rsi_period = int(round(rsi_config['rsi_period_min'] + (period_range * period_step)))
        else:
            current_rsi_period = rsi_config['rsi_period_min']

        state.current_rsi_period = current_rsi_period
        
        return True

    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"เกิดข้อผิดพลาดในการอัพเดทค่าตลาด: {str(e)}", "red")
        message(symbol, f"Error: {error_traceback}", "red")
        return False
    
def calculate_rsi(close_prices, length):
    """คำนวณ RSI โดยใช้ numpy (คงฟังก์ชันเดิมไว้เพราะทำงานได้ดีอยู่แล้ว)"""
    if len(close_prices) < length + 1:
        return np.zeros_like(close_prices)
        
    deltas = np.diff(close_prices)
    seed = deltas[:length+1]
    up = seed[seed >= 0].sum()/length
    down = -seed[seed < 0].sum()/length
    
    if down == 0:
        if up == 0:
            rs = 1.0
        else:
            rs = float('inf')
    else:
        rs = up/down
        
    rsi = np.zeros_like(close_prices)
    rsi[:length] = 100. - 100./(1. + rs)

    for i in range(length, len(close_prices)):
        delta = deltas[i-1]
        if delta > 0:
            upval = delta
            downval = 0.
        else:
            upval = 0.
            downval = -delta

        up = (up*(length-1) + upval)/length
        down = (down*(length-1) + downval)/length
        
        if down == 0:
            if up == 0:
                rs = 1.0
            else:
                rs = float('inf')
        else:
            rs = up/down
            
        rsi[i] = 100. - 100./(1. + rs)

    return np.clip(rsi, 0, 100)

async def get_rsi_cross_last_candle(api_key, api_secret, symbol, timeframe, state, candle_index=0):
    """คำนวณ RSI cross โดยใช้ค่า period ที่คำนวณไว้แล้ว"""
    exchange = None
    try:
        # ใช้ค่า RSI Period ที่คำนวณไว้แล้ว
        current_rsi_period = state.current_rsi_period
        if current_rsi_period is None:
            message(symbol, "ไม่พบค่า RSI Period ที่คำนวณไว้", "yellow")
            return {
                'status': False,
                'type': None,
                'candle': None,
                'error': 'ไม่พบค่า RSI Period'
            }

        # ดึงข้อมูลและคำนวณ RSI
        ohlcv = await fetch_ohlcv(symbol, timeframe, limit=100)
        
        if not ohlcv or len(ohlcv) < current_rsi_period + 10:
            return {
                'status': False,
                'type': None,
                'candle': None,
                'error': 'ข้อมูลไม่เพียงพอสำหรับการคำนวณ RSI'
            }
        
        closed_ohlcv = ohlcv[:-1]
        df = pd.DataFrame(closed_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        local_tz = pytz.timezone('Asia/Bangkok')
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms').dt.tz_localize(pytz.UTC).dt.tz_convert(local_tz)
        
        with np.errstate(divide='ignore', invalid='ignore'):
            df['rsi'] = calculate_rsi(df['close'].values, current_rsi_period)
        
        if len(df) < 2 + candle_index:
            return {
                'status': False,
                'type': None,
                'candle': None,
                'error': 'ข้อมูลไม่เพียงพอสำหรับการตรวจสอบ crossover'
            }
            
        last_closed_rsi = df['rsi'].iloc[-(1 + candle_index)]
        prev_closed_rsi = df['rsi'].iloc[-(2 + candle_index)]
        
        if np.isnan(last_closed_rsi) or np.isnan(prev_closed_rsi):
            return {
                'status': False,
                'type': None,
                'candle': None,
                'error': 'ค่า RSI เป็น NaN'
            }
        
        result = {
            'status': False,
            'type': None,
            'rsi_period_used': current_rsi_period,
            'atr_values': {
                f'atr_{state.config.rsi_period["atr"]["length1"]}': state.current_atr_length_1,
                f'atr_{state.config.rsi_period["atr"]["length2"]}': state.current_atr_length_2
            },
            'candle': {
                'open': float(df['open'].iloc[-(1 + candle_index)]),
                'high': float(df['high'].iloc[-(1 + candle_index)]),
                'low': float(df['low'].iloc[-(1 + candle_index)]),
                'close': float(df['close'].iloc[-(1 + candle_index)]),
                'volume': float(df['volume'].iloc[-(1 + candle_index)]),
                'timestamp': int(df['timestamp'].iloc[-(1 + candle_index)].timestamp() * 1000),
                'time': df['timestamp'].iloc[-(1 + candle_index)].strftime('%d/%m/%Y %H:%M'),
                'rsi': round(float(last_closed_rsi), 2)
            }
        }
        
        # ตรวจสอบจุดตัด RSI
        if prev_closed_rsi >= state.config.rsi_overbought and last_closed_rsi < state.config.rsi_overbought:
            result['status'] = True
            result['type'] = 'crossunder'
        elif prev_closed_rsi <= state.config.rsi_oversold and last_closed_rsi > state.config.rsi_oversold:
            result['status'] = True
            result['type'] = 'crossover'
        elif prev_closed_rsi < state.config.rsi_overbought and last_closed_rsi >= state.config.rsi_overbought:
            result['status'] = True
            result['type'] = 'crossover'
        elif prev_closed_rsi > state.config.rsi_oversold and last_closed_rsi <= state.config.rsi_oversold:
            result['status'] = True
            result['type'] = 'crossunder'

        """message(symbol, f"RSI: {result['candle']['rsi']} " +
                f"(Period: {current_rsi_period}, " +
                f"ATR4: {state.current_atr_length_1:.8f}, " +
                f"ATR200: {state.current_atr_length_2:.8f})", "blue")"""
        
        return result

    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"เกิดข้อผิดพลาดในการคำนวณ RSI: {str(e)}", "red")
        message(symbol, f"Error: {error_traceback}", "red")
        return {
            'status': False,
            'type': None,
            'candle': None,
            'error': str(e)
        }

async def _handle_rsi_signals(api_key, api_secret, symbol, state, position_side, rsi_cross, ohlcv):
    """จัดการสัญญาณ RSI และสร้าง entry orders"""
    try:
        if rsi_cross['type'] in ['crossunder', 'crossover']:
            state.last_candle_cross = rsi_cross

        if state.is_in_position and position_side:
            # จัดการ position ที่มีอยู่
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
                        state.current_stoploss = state.last_focus_price
                        state.last_focus_price = None
                    except Exception as e:
                        message(symbol, f"เกิดข้อผิดพลาดในการเปลี่ยน stop loss: {str(e)}", "red")

        elif not state.is_in_position:  # ไม่มี position
            await clear_all_orders(api_key, api_secret, symbol)
            
            if 'candle' in rsi_cross:
                cross_candle = rsi_cross['candle']
                
                # ใช้ราคาจาก state
                current_price = state.current_price
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
                    # คำนวณ quantity
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

                    adjusted_quantity = await adjust_quantity_for_stoploss(
                        api_key, api_secret, symbol,
                        entry_price, stoploss_price,
                        initial_quantity, state
                    )

                    # สร้าง entry order
                    entry_order = None
                    if should_market_entry:
                        message(symbol, f"ราคาผ่านจุด trigger แล้ว - เข้าด้วย MARKET", "yellow")
                        entry_order = await create_order(
                            api_key, api_secret,
                            symbol=symbol,
                            side=entry_side,
                            price='now',
                            quantity=str(adjusted_quantity),
                            order_type='MARKET',
                            martingale_multiplier=state.martingale_multiplier
                        )
                    else:
                        entry_order = await create_order(
                            api_key, api_secret,
                            symbol=symbol,
                            side=entry_side,
                            price=str(entry_trigger_price),
                            quantity=str(adjusted_quantity),
                            order_type='STOP_MARKET',
                            martingale_multiplier=state.martingale_multiplier
                        )

                    if entry_order:
                        # สร้าง Stoploss Order
                        stoploss_order = await create_order(
                            api_key, api_secret,
                            symbol=symbol,
                            side=stoploss_side,
                            price=str(stoploss_price),
                            quantity='MAX',
                            order_type='STOPLOSS_MARKET',
                            martingale_multiplier=state.martingale_multiplier
                        )
                        
                        if stoploss_order:
                            # อัพเดทสถานะ orders
                            state.entry_side = entry_side
                            state.entry_price = entry_trigger_price
                            state.entry_stoploss_price = stoploss_price

                            if should_market_entry:
                                message(symbol, f"เข้า {entry_side.upper()} ด้วย MARKET ORDER สำเร็จ", "green")
                                
                                # อัพเดทสถานะ position
                                state.reset_position_data()
                                state.is_in_position = True
                                state.global_position_data.update({
                                    'entry_price': float(entry_order['average']),
                                    'entry_time': datetime.now(pytz.UTC),
                                    'position_side': entry_side,
                                })
                                
                                # ตั้งค่า TP orders
                                current_candle = state.current_candle
                                if current_candle:
                                    state.entry_candle = current_candle
                                    tp_orders = await setup_take_profit_orders(
                                        api_key, api_secret, symbol,
                                        state.global_position_data['entry_price'],
                                        state.global_position_data['position_side'],
                                        state.config.timeframe,
                                        state
                                    )
                                else:
                                    message(symbol, "ไม่สามารถดึงข้อมูลแท่งเทียนสำหรับตั้ง TP ได้", "red")

                                # รีเซ็ต entry orders
                                state.entry_orders = None
                                state.entry_side = None
                                state.entry_price = None
                                state.entry_stoploss_price = None
                            else:
                                state.entry_orders = {
                                    'entry_order': entry_order,
                                    'stoploss_order': stoploss_order,
                                    'is_market_entry': should_market_entry
                                }
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

async def _handle_position_swap(api_key, api_secret, symbol, state, price, position_side):
    """จัดการการสลับ position"""
    try:
        should_swap = False
        new_side = None
        new_stoploss = None
        current_candle = state.current_candle

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
            price = float(current_candle['low'])
            if price < state.last_focus_price * PRICE_DECREASE:
                should_swap = True
                new_side = 'sell'
                new_stoploss = state.last_candle_cross['candle']['high'] * PRICE_INCREASE
        elif position_side == 'sell':
            max_price = float(current_candle['high'])
            if max_price > state.last_focus_price * PRICE_INCREASE:
                should_swap = True
                new_side = 'buy'
                new_stoploss = state.last_candle_cross['candle']['low'] * PRICE_DECREASE

        if should_swap:
            message(symbol, f"สลับ position จาก {position_side} เนื่องจาก:", "magenta")
            message(symbol, f"- มีสัญญาณ {state.last_candle_cross['type']}", "magenta")
            message(symbol, f"- ราคาปัจจุบัน: {price}", "magenta")
            message(symbol, f"- ราคาอ้างอิง: {state.last_focus_price}", "magenta")

            state.is_swapping = True
            
            # บันทึกข้อมูลเก่าก่อนสลับ
            old_entry_price = state.global_position_data['entry_price']
            old_side = state.global_position_data['position_side']

            try:
                # ล้าง orders ทั้งหมดก่อน
                message(symbol, "เคลียร์ orders ทั้งหมดก่อน swap position", "yellow")
                await clear_all_orders(api_key, api_secret, symbol)
                
                """# รอให้แน่ใจว่า orders ถูกเคลียร์จริงๆ
                await asyncio.sleep(1)  # รอสักครู่
                
                # ตรวจสอบว่าไม่มี orders ค้าง
                orders = await exchange.fetch_open_orders(symbol)
                if orders:
                    message(symbol, f"ยังมี orders ค้างอยู่ {len(orders)} orders รอเคลียร์อีกครั้ง", "yellow")
                    await clear_all_orders(api_key, api_secret, symbol)
                    await asyncio.sleep(1)  # รออีกครั้ง"""
                
                # ดำเนินการ swap
                message(symbol, "เริ่มทำการ swap position", "yellow")
                await swap_position_side(api_key, api_secret, symbol)

                # สร้าง stoploss order ใหม่
                stoploss_order = await create_order(
                    api_key, api_secret, symbol=symbol,
                    side='buy' if new_side == 'sell' else 'sell',
                    price=str(new_stoploss),
                    quantity='MAX',
                    order_type='STOPLOSS_MARKET',
                    martingale_multiplier=state.martingale_multiplier
                )

                if stoploss_order:
                    message(symbol, f"สลับ position จาก {position_side} สำเร็จ", "magenta")
                    
                    # บันทึกการออกจาก position เดิม
                    exit_price = state.current_price
                    await record_trade(
                        api_key, api_secret, symbol,
                        'BUY' if old_side == 'buy' else 'SELL',
                        old_entry_price, exit_price, state.config.entry_amount,
                        f'Position Swapped to {new_side.capitalize()}!',
                        state
                    )

                    # อัพเดทข้อมูล position ใหม่
                    state.reset_position_data()
                    state.is_in_position = True
                    state.global_position_data.update({
                        'entry_price': price,
                        'entry_time': datetime.now(pytz.UTC),
                        'position_side': new_side,
                    })
                    
                    # อัพเดท entry candle
                    state.entry_candle = await get_current_candle(api_key, api_secret, symbol, state.config.timeframe)
                    
                    # สร้าง Take Profit Orders ใหม่
                    tp_orders = await setup_take_profit_orders(
                        api_key, api_secret, symbol,
                        state.global_position_data['entry_price'],
                        state.global_position_data['position_side'],
                        state.config.timeframe,
                        state
                    )

                    state.is_swapping = False
                    state.last_focus_price = None
                    state.current_stoploss = new_stoploss
                    state.save_state()
                    
                else:
                    message(symbol, "ไม่สามารถสร้าง Stoploss Order ได้ หลัง swap", "red")
                    state.is_swapping = False

            except Exception as e:
                message(symbol, f"เกิดข้อผิดพลาดระหว่างการ swap: {str(e)}", "red")
                state.is_swapping = False
                # อาจจะต้องมีการจัดการเพิ่มเติมในกรณีที่เกิดข้อผิดพลาด

    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"Error in position swap handling: {str(e)}", "red")
        message(symbol, f"Error: {error_traceback}", "red")
        state.is_swapping = False

async def load_trading_config():
    """โหลดการตั้งค่าการเทรด"""
    try:
        config_list = []
        
        if not os.path.exists('json/index.json'):
            os.makedirs('json', exist_ok=True)
            # Convert TRADING_CONFIG to index.json format
            with open('json/index.json', 'w') as f:
                json.dump(TRADING_CONFIG, f, indent=2)
            message("SYSTEM", "สร้างไฟล์ index.json จาก TRADING_CONFIG", "yellow")
            config_list = TRADING_CONFIG
        else:
            # Load existing index.json
            with open('json/index.json', 'r') as f:
                config_list = json.load(f)
            
        # Convert config_list to dictionary with symbol as key
        trading_config = {}
        for config in config_list:
            if isinstance(config, dict) and 'symbol' in config:
                trading_config[config['symbol']] = config
        
        if not trading_config:
            message("SYSTEM", "ไม่พบข้อมูล config ที่ถูกต้อง ใช้ค่าเริ่มต้น", "yellow")
            # Use default config as fallback
            for config in TRADING_CONFIG:
                if isinstance(config, dict) and 'symbol' in config:
                    trading_config[config['symbol']] = config
                    
        return trading_config
            
    except Exception as e:
        error_traceback = traceback.format_exc()
        message("SYSTEM", f"เกิดข้อผิดพลาดในการโหลด Trading Config: {str(e)}", "red")
        message("SYSTEM", f"Error: {error_traceback}", "red")
        
        # Fallback to default config
        trading_config = {}
        for config in TRADING_CONFIG:
            if isinstance(config, dict) and 'symbol' in config:
                trading_config[config['symbol']] = config
        message("SYSTEM", "ใช้ค่า default จาก TRADING_CONFIG แทน", "yellow")
        return trading_config

async def get_current_candle(api_key, api_secret, symbol, timeframe):
    """ดึงข้อมูลแท่งเทียนปัจจุบัน"""
    exchange = await create_future_exchange(api_key, api_secret)
    try:
        ohlcv = await fetch_ohlcv(symbol, timeframe, limit=1)
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
        message(symbol, f"Error: {error_traceback}", "red")
    finally:
        await exchange.close()
    return None

async def adjust_quantity_for_stoploss(api_key: str, api_secret: str, symbol: str, 
                                     entry_price: float, stoploss_price: float, 
                                     quantity: float, state: SymbolState) -> float:
    """ปรับปริมาณตาม stoploss และตรวจสอบ minimum notional value"""
    try:
        config = state.config
        current_percent = abs((entry_price - stoploss_price) / entry_price * 100)

        def check_and_adjust_notional(qty: float) -> float:
            """ตรวจสอบและปรับ quantity ให้ได้ตาม minimum notional"""
            notional = qty * entry_price
            if notional < MIN_NOTIONAL:
                adjusted_qty = MIN_NOTIONAL / entry_price
                message(symbol, f"ปรับ quantity เพื่อให้ได้ minimum notional {MIN_NOTIONAL} USDT " +
                              f"(จาก {qty:.8f} เป็น {adjusted_qty:.8f})", "blue")
                return adjusted_qty
            return qty

        # ถ้ามี fix_stoploss ใช้ค่านี้อย่างเดียว
        if config.fix_stoploss is not None:
            target_percent = float(config.fix_stoploss)
            adjustment_ratio = target_percent / current_percent
            new_quantity = quantity * adjustment_ratio
            message(symbol, f"ปรับ quantity ตาม fix stoploss {target_percent}% " +
                          f"(SL ปัจจุบัน: {current_percent:.2f}%, ratio: {adjustment_ratio:.4f})", "blue")
            
            # ตรวจสอบและปรับ minimum notional
            new_quantity = check_and_adjust_notional(new_quantity)
            return await get_adjust_precision_quantity(symbol, new_quantity)

        # เช็ค min_stoploss
        if config.min_stoploss is not None and current_percent < float(config.min_stoploss):
            target_percent = float(config.min_stoploss)
            adjustment_ratio = target_percent / current_percent
            new_quantity = quantity * adjustment_ratio
            message(symbol, f"เพิ่ม quantity ตาม min stoploss {target_percent}% " +
                          f"(SL ปัจจุบัน: {current_percent:.2f}%, ratio: {adjustment_ratio:.4f})", "blue")
            
            # ตรวจสอบและปรับ minimum notional
            new_quantity = check_and_adjust_notional(new_quantity)
            return await get_adjust_precision_quantity(symbol, new_quantity)

        # เช็ค max_stoploss
        if config.max_stoploss is not None and current_percent > float(config.max_stoploss):
            target_percent = float(config.max_stoploss)
            adjustment_ratio = target_percent / current_percent
            new_quantity = quantity * adjustment_ratio
            message(symbol, f"ลด quantity ตาม max stoploss {target_percent}% " +
                          f"(SL ปัจจุบัน: {current_percent:.2f}%, ratio: {adjustment_ratio:.4f})", "blue")
            
            # ตรวจสอบและปรับ minimum notional
            new_quantity = check_and_adjust_notional(new_quantity)
            return await get_adjust_precision_quantity(symbol, new_quantity)

        # ตรวจสอบ minimum notional สำหรับกรณีที่ไม่มีการปรับ stoploss
        return await get_adjust_precision_quantity(symbol, check_and_adjust_notional(quantity))

    except Exception as e:
        message(symbol, f"Error adjusting quantity: {str(e)}", "red")
        return quantity

def timeframe_to_seconds(timeframe):
    """แปลง timeframe เป็นวินาที"""
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
    """แปลง timeframe เป็นมิลลิวินาที"""
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

async def run_with_error_handling(coro, symbol, max_retries=5, retry_delay=60):
    """ฟังก์ชันจัดการ error และ retry"""
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

async def show_trading_summary(symbol: str, state: SymbolState):
    """แสดงสรุปผลการเทรด"""
    try:
        perf = state.performance_data
        if perf['trades_count'] > 0:
            win_rate = (perf['winning_trades'] / perf['trades_count']) * 100
            message(symbol, "====== สรุปผลการเทรด ======", "magenta")
            message(symbol, f"จำนวนเทรดทั้งหมด: {perf['trades_count']}", "magenta")
            message(symbol, f"เทรดกำไร: {perf['winning_trades']} ครั้ง", "magenta")
            message(symbol, f"เทรดขาดทุน: {perf['losing_trades']} ครั้ง", "magenta")
            message(symbol, f"Win Rate: {win_rate:.2f}%", "magenta")
            message(symbol, f"กำไรรวม: {perf['total_profit']:.2f} USDT", "magenta")
            message(symbol, f"กำไรสูงสุด: {perf['largest_profit']:.2f} USDT", "magenta")
            message(symbol, f"ขาดทุนสูงสุด: {perf['largest_loss']:.2f} USDT", "magenta")
            message(symbol, "===========================", "magenta")
        else:
            message(symbol, "ยังไม่มีประวัติการเทรด", "yellow")
    except Exception as e:
        message(symbol, f"Error showing trading summary: {str(e)}", "red")

# Utility functions for date/time handling
def get_current_timestamp():
    """รับ timestamp ปัจจุบัน"""
    return int(time.time() * 1000)

def get_timeframe_start(timestamp, timeframe):
    """คำนวณเวลาเริ่มต้นของ timeframe"""
    dt = datetime.fromtimestamp(timestamp / 1000, tz=pytz.UTC)
    if timeframe.endswith('m'):
        minutes = int(timeframe[:-1])
        dt = dt.replace(minute=dt.minute - (dt.minute % minutes),
                       second=0, microsecond=0)
    elif timeframe.endswith('h'):
        hours = int(timeframe[:-1])
        dt = dt.replace(hour=dt.hour - (dt.hour % hours),
                       minute=0, second=0, microsecond=0)
    elif timeframe.endswith('d'):
        dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(dt.timestamp() * 1000)

def format_timestamp(timestamp):
    """แปลง timestamp เป็นเวลาที่อ่านได้"""
    return datetime.fromtimestamp(timestamp / 1000, tz=pytz.UTC).strftime('%Y-%m-%d %H:%M:%S %Z')

async def main():
    price_tracker = None
    kline_tracker = None
    tracker_tasks = []
    
    try:
        # โหลด Trading Config
        trading_config = await load_trading_config()
        if not trading_config:
            message("SYSTEM", "ไม่สามารถโหลด Trading Config ได้ กรุณาตรวจสอบไฟล์ index.json", "red")
            return
            
        # เริ่มต้น price tracker และ kline tracker
        price_tracker = get_price_tracker()
        kline_tracker = get_kline_tracker()
        
        # โหลดและตรวจสอบการตั้งค่าสำหรับทุกเหรียญ
        symbol_configs = {}
        
        try:
            with open('json/index.json', 'r') as f:
                configs = json.load(f)
                for config in configs:
                    symbol = config['symbol'].upper()
                    if 'timeframe' not in config:
                        message("SYSTEM", f"ไม่พบ timeframe สำหรับ {symbol} ข้ามการทำงาน", "yellow")
                        continue

                    message("SYSTEM", f"กำลังโหลดข้อมูล {symbol} ({config['timeframe']})", "blue")
                    symbol_configs[symbol] = config
                    clean_symbol = symbol.lower()
                    price_tracker.subscribe_symbol(clean_symbol)
                    await kline_tracker.initialize_symbol_data(symbol, config['timeframe'])
                    # เพิ่มดีเลย์ระหว่างการโหลดข้อมูลแต่ละเหรียญ
                    await asyncio.sleep(1)
                    
        except Exception as e:
            message("SYSTEM", f"เกิดข้อผิดพลาดในการโหลดการตั้งค่า: {str(e)}", "red")
            return

        if not symbol_configs:
            message("SYSTEM", "ไม่พบคู่เทรดที่ต้องการทำงาน กรุณาตรวจสอบไฟล์ index.json", "red")
            return
        
        # เริ่ม trackers
        tracker_tasks = [
            asyncio.create_task(price_tracker.start()),
            asyncio.create_task(kline_tracker.start())
        ]
        
        # รอให้ trackers เริ่มต้น
        await asyncio.sleep(2)
        
        # อัพเดท symbol data ครั้งเดียว
        #await update_symbol_data(api_key, api_secret)
        
        # สร้าง state objects สำหรับทุกเหรียญ
        symbol_states = {symbol: SymbolState(symbol) for symbol in symbol_configs}
        
        # Main loop
        while True:
            try:
                # ประมวลผลทีละเหรียญ
                for symbol, state in symbol_states.items():
                    await run_sequential_bot(api_key, api_secret, symbol, state)
                    # เว้น 1 วินาทีระหว่างแต่ละเหรียญ
                    await asyncio.sleep(1)
                
                # เว้น 5 วินาทีก่อนเริ่มรอบใหม่
                #message("SYSTEM", "รอ 5 วินาทีก่อนเริ่มรอบใหม่...", "blue")
                await asyncio.sleep(1)
                
            except Exception as e:
                error_traceback = traceback.format_exc()
                message("SYSTEM", f"เกิดข้อผิดพลาดในรอบการทำงาน: {str(e)}", "red")
                message("SYSTEM", f"Error: {error_traceback}", "red")
                await asyncio.sleep(5)
                
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
        
        # ยกเลิก tracker tasks
        for task in tracker_tasks:
            if not task.done():
                task.cancel()
        
        # หยุด trackers
        if price_tracker:
            await price_tracker.stop()
        if kline_tracker:
            await kline_tracker.stop()
        
        # รอให้ tracker tasks ถูกยกเลิกเสร็จสิ้น
        if tracker_tasks:
            await asyncio.gather(*tracker_tasks, return_exceptions=True)
        
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
        loop = asyncio.get_event_loop()
        pending = asyncio.all_tasks(loop=loop)
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()
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
            
            # Update ATR if needed (every 4 hours)
            if (not self.current_market_data['atr_last_update'] or 
                datetime.now(pytz.UTC) - self.current_market_data['atr_last_update'] > timedelta(hours=4)):
                self.current_market_data['atr'] = await calculate_atr(
                    api_key, api_secret, self.symbol, self.config.timeframe, self
                )
                self.current_market_data['atr_last_update'] = datetime.now(pytz.UTC)
                
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
            """Helper function to convert datetime to ISO format string"""
            if isinstance(dt, datetime):
                return dt.isoformat()
            return dt

        def process_dict(d):
            """Helper function to process dictionary values"""
            return {k: datetime_to_iso(v) if isinstance(v, datetime) else v 
                for k, v in d.items()}

        current_state = {
            'current_orders': self.current_orders,
            'current_candle': self.current_candle,
            'current_price': self.current_price,
            'current_stoploss': self.current_stoploss,
            'current_market_data': process_dict(self.current_market_data),
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
            'performance_data': process_dict(self.performance_data)
        }
        
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        with open(self.state_file, 'w') as f:
            json.dump(current_state, f, indent=2)

    def load_state(self):
        """โหลดสถานะทั้งหมดจากไฟล์"""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    saved_state = json.load(f)
                    
                def parse_datetime(dt_str):
                    """Helper function to parse datetime string"""
                    if dt_str and isinstance(dt_str, str):
                        return datetime.fromisoformat(dt_str)
                    return dt_str

                def process_dict(d):
                    """Helper function to process dictionary values"""
                    if not isinstance(d, dict):
                        return d
                    return {k: parse_datetime(v) if k.endswith('_time') or k.endswith('_update') else v 
                        for k, v in d.items()}

                # Load all cached data
                self.current_orders = saved_state.get('current_orders')
                self.current_candle = saved_state.get('current_candle')
                self.current_price = saved_state.get('current_price')
                self.current_stoploss = saved_state.get('current_stoploss')
                self.current_market_data = process_dict(saved_state.get('current_market_data', self.current_market_data))
                
                # Load position states
                self.is_in_position = saved_state.get('is_in_position', False)
                self.is_swapping = saved_state.get('is_swapping', False)
                self.is_wait_candle = saved_state.get('is_wait_candle', False)
                self.global_position_data = process_dict(saved_state.get('global_position_data', self.global_position_data))
                
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
                self.tp_levels_hit = saved_state.get('tp_levels_hit', self.tp_levels_hit)
                
                # Load performance data
                self.performance_data = process_dict(saved_state.get('performance_data', self.performance_data))
                
                #message(self.symbol, f"โหลดสถานะเสร็จสมบูรณ์ (Timeframe: {self.config.timeframe})", "cyan")
                return True
                    
            except Exception as e:
                message(self.symbol, f"เกิดข้อผิดพลาดในการโหลดสถานะ: {str(e)}", "red")
                return False
                    
        message(self.symbol, f"ไม่พบไฟล์สถานะ เริ่มต้นด้วยค่าเริ่มต้น (Timeframe: {self.config.timeframe})", "yellow")
        return False

class TradingConfig:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self._load_config()
        
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
                self.take_profits = symbol_config.get('take_profits', {
                    'move_sl_to_entry_at_tp1': True,
                    'levels': [
                        {'id': 'tp1', 'size': '5%', 'target_atr': 1},
                        {'id': 'tp2', 'size': '20%', 'target_atr': 2},
                        {'id': 'tp3', 'size': '25%', 'target_atr': 3},
                        {'id': 'tp4', 'size': '25%', 'target_atr': 4}
                    ]
                })
            else:
                # Use default settings if no config found
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
        
        # อัพเดทข้อมูลตลาดทั้งหมดในครั้งเดียว
        await state.update_market_data(api_key, api_secret)
        
        # ตรวจสอบและดำเนินการตามสถานะปัจจุบัน
        if state.current_price is None:
            message(symbol, "ไม่สามารถดึงราคาตลาดได้ ข้ามรอบนี้", "yellow")
            return

        # Position management
        if state.is_in_position and not state.is_swapping:
            if not await check_position(api_key, api_secret, symbol):
                await _handle_position_close(api_key, api_secret, symbol, state, state.current_price)
            else:
                # จัดการ position ที่มีอยู่
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
                state.config.rsi_period,
                state.config.rsi_oversold,
                state.config.rsi_overbought
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
                            order_type='MARKET'
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
                            order_type='LIMIT'
                        )
                    else:
                        message(symbol, f"ตั้ง STOP_MARKET ที่ {entry_trigger_price:.8f}", "yellow")
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
        message(symbol, f"Error in new candle handling: {str(e)}", "red")

async def _handle_stoploss_adjustment(api_key, api_secret, symbol, state, position_side, price):
    """จัดการการปรับ stoploss"""
    try:
        if position_side == 'buy':
            if price > state.last_candle_cross['candle']['high'] * PRICE_INCREASE:
                new_stoploss = state.last_candle_cross['candle']['low'] * PRICE_DECREASE
                await change_stoploss_to_price(api_key, api_secret, symbol, new_stoploss)
                message(symbol, f"ปรับ Stop Loss เป็น {new_stoploss:.8f}", "cyan")
                state.is_wait_candle = False
                state.current_stoploss = new_stoploss
        elif position_side == 'sell':
            if price < state.last_candle_cross['candle']['low'] * PRICE_DECREASE:
                new_stoploss = state.last_candle_cross['candle']['high'] * PRICE_INCREASE
                await change_stoploss_to_price(api_key, api_secret, symbol, new_stoploss)
                message(symbol, f"ปรับ Stop Loss เป็น {new_stoploss:.8f}", "cyan")
                state.is_wait_candle = False
                state.current_stoploss = new_stoploss
    except Exception as e:
        message(symbol, f"Error in stoploss adjustment: {str(e)}", "red")

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

        # ดึง ATR
        atr = await calculate_atr(api_key, api_secret, symbol, timeframe, state, length=7)
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
        message(symbol, f"เกิดข้อผิดพลาดในการสร้าง Take Profit Orders: {str(e)}", "red")
        message(symbol, f"Error: {error_traceback}", "red")
        return []

async def _handle_entry_orders(api_key, api_secret, symbol, state, price, exchange):
    """จัดการ entry orders"""
    try:
        if not state.entry_orders:
            return

        # เช็คสถานะ position
        has_position = await check_position(api_key, api_secret, symbol)
        
        # ถ้า state บอกว่าไม่มี position แต่จริงๆ มี แสดงว่า order ทำงานแล้ว
        if not state.is_in_position and has_position:
            message(symbol, f"Entry order ทำงานแล้ว กำลังอัพเดทสถานะ", "green")
            
            # อัพเดทสถานะ position
            state.reset_position_data()
            state.is_in_position = True
            
            # ดึงข้อมูล position จริงจาก exchange
            try:
                positions = await exchange.fetch_positions([symbol])
                current_position = next((pos for pos in positions if float(pos['contracts']) != 0), None)
                
                if current_position:
                    state.global_position_data.update({
                        'entry_price': float(current_position['entryPrice']),
                        'entry_time': datetime.now(pytz.UTC),
                        # แปลง side จาก long/short เป็น buy/sell
                        'position_side': 'buy' if current_position['side'] == 'long' else 'sell',
                        'position_size': float(current_position['contracts']),
                        'leverage': int(current_position['leverage']),
                        'margin_type': current_position['marginType']
                    })
                    
                    # ตั้งค่า entry candle
                    state.entry_candle = state.current_candle
                    
                    # สร้าง Take Profit Orders
                    tp_orders = await setup_take_profit_orders(
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
                    message(symbol, "ไม่พบข้อมูล position", "red")
                    
            except Exception as e:
                message(symbol, f"เกิดข้อผิดพลาดในการดึงข้อมูล position: {str(e)}", "red")
            
            state.save_state()
            return

        # ถ้ายังไม่มี position ให้เช็คว่าต้องยกเลิก order หรือไม่
        if current_candle := state.current_candle:
            max_price = float(current_candle['high'])
            min_price = float(current_candle['low'])
            
            # เช็ค stoploss
            if state.entry_side == 'long' and min_price < state.entry_stoploss_price:
                await clear_all_orders(api_key, api_secret, symbol)
                message(symbol, f"ยกเลิก Orders เนื่องจากราคาต่ำกว่า stoploss", "yellow")
                message(symbol, f"ข้อมูลเพิ่มเติม: min_price:{min_price} entry_stoploss_price:{state.entry_stoploss_price}", "yellow")
                
                # รีเซ็ตสถานะ
                state.reset_position_data()
                state.entry_orders = None
                state.entry_side = None
                state.entry_price = None
                state.entry_stoploss_price = None
                
            elif state.entry_side == 'short' and max_price > state.entry_stoploss_price:
                await clear_all_orders(api_key, api_secret, symbol)
                message(symbol, f"ยกเลิก Orders เนื่องจากราคาสูงกว่า stoploss", "yellow")
                message(symbol, f"ข้อมูลเพิ่มเติม: max_price:{max_price} entry_stoploss_price:{state.entry_stoploss_price}", "yellow")
                
                # รีเซ็ตสถานะ
                state.reset_position_data()
                state.entry_orders = None
                state.entry_side = None
                state.entry_price = None
                state.entry_stoploss_price = None
            
            state.save_state()

    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"เกิดข้อผิดพลาดในการจัดการ Entry Orders: {str(e)}", "red")
        message(symbol, f"Error Traceback: {error_traceback}", "red")
        
async def manage_position_profit(api_key: str, api_secret: str, symbol: str, state: SymbolState):
    """จัดการ position profit รวมถึงการย้าย stoploss ตามการตั้งค่า"""
    exchange = None
    try:
        if not state.is_in_position:
            return

        exchange = await create_future_exchange(api_key, api_secret)

        current_stoploss = state.current_stoploss
        atr = state.current_market_data['atr']
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

        # หา TP1 จากการตั้งค่า
        tp1_config = next((level for level in tp_config['levels'] if level['id'] == 'tp1'), None)
        if not tp1_config:
            return

        # คำนวณราคา TP1
        if position_side == 'buy':
            tp1_base = entry_price + (atr * tp1_config['target_atr'])
            tp1_price = tp1_base * (PRICE_INCREASE + (PRICE_CHANGE_THRESHOLD * (tp1_config['target_atr'] * 2)))
            current_profit_atr = (max_price - entry_price) / atr
            current_profit_percent = ((max_price - entry_price) / entry_price) * 100
        else:
            tp1_base = entry_price - (atr * tp1_config['target_atr'])
            tp1_price = tp1_base * (PRICE_DECREASE - (PRICE_CHANGE_THRESHOLD * (tp1_config['target_atr'] * 2)))
            current_profit_atr = (entry_price - min_price) / atr
            current_profit_percent = ((entry_price - min_price) / entry_price) * 100

        # จัดการ TP1 - ย้าย stoploss ตามการตั้งค่า
        if ((position_side == 'buy' and max_price >= tp1_price) or
            (position_side == 'sell' and min_price <= tp1_price)) and not state.tp_levels_hit['tp1']:
            
            message(symbol, f"กำไรถึงระดับ TP1 ({current_profit_atr:.2f} ATR, {current_profit_percent:.2f}%)", "cyan")

            # ตรวจสอบว่าต้องย้าย SL มาที่จุดเข้าหรือไม่
            if tp_config.get('move_sl_to_entry_at_tp1', True):
                try:
                    if position_side == 'buy':
                        new_stoploss = entry_price * ( PRICE_DECREASE - PRICE_CHANGE_THRESHOLD )
                        if current_stoploss < new_stoploss:
                            message(symbol, f"กำลังปรับ stoploss ไปที่จุดเข้า {new_stoploss:.8f}", "cyan")
                            await change_stoploss_to_price(api_key, api_secret, symbol, new_stoploss)
                            state.tp_levels_hit['tp1'] = True
                            state.current_stoploss = new_stoploss
                            message(symbol, "ปรับ stoploss เรียบร้อย", "cyan")
                    else:  # sell
                        new_stoploss = entry_price * ( PRICE_INCREASE + PRICE_CHANGE_THRESHOLD)
                        if current_stoploss > new_stoploss:
                            message(symbol, f"กำลังปรับ stoploss ไปที่จุดเข้า {new_stoploss:.8f}", "cyan")
                            await change_stoploss_to_price(api_key, api_secret, symbol, new_stoploss)
                            state.tp_levels_hit['tp1'] = True
                            state.current_stoploss = new_stoploss
                            message(symbol, "ปรับ stoploss เรียบร้อย", "cyan")
                except Exception as e:
                    message(symbol, f"เกิดข้อผิดพลาดในการปรับ stoploss: {str(e)}", "red")
            else:
                message(symbol, "ข้าม การย้าย stoploss ไปจุดเข้าตามการตั้งค่า", "cyan")
                state.tp_levels_hit['tp1'] = True

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

            # คำนวณกำไร/ขาดทุน
            if action in ['BUY', 'SELL']:
                profit_loss = ((actual_exit_price - actual_entry_price) if action == 'BUY' else 
                             (actual_entry_price - actual_exit_price)) * actual_amount
            else:  # action == 'SWAP'
                profit_loss = (actual_exit_price - actual_entry_price) * actual_amount

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
                order_type='STOPLOSS_MARKET'
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

async def calculate_atr(api_key, api_secret, symbol, timeframe, state: SymbolState, length=7):
    """คำนวณ ATR (Average True Range)"""
    try:
        if timeframe not in state.current_market_data.get('atr_cache', {}):
            exchange = await create_future_exchange(api_key, api_secret)
            ohlcv = await fetch_ohlcv(symbol, timeframe, limit=length + 1)
            
            if len(ohlcv) < length + 1:
                message(symbol, f"ข้อมูลไม่พอสำหรับคำนวณ ATR (ต้องการ {length + 1} แท่ง)", "yellow")
                return None

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

            # Cache the result
            if 'atr_cache' not in state.current_market_data:
                state.current_market_data['atr_cache'] = {}
            state.current_market_data['atr_cache'][timeframe] = rma
            state.current_market_data['atr_last_update'] = datetime.now(pytz.UTC)
            
            return rma
        
        return state.current_market_data['atr_cache'][timeframe]

    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"เกิดข้อผิดพลาดในการคำนวณ ATR: {str(e)}", "red")
        message(symbol, f"Error: {error_traceback}", "red")
        return None

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

            # ดำเนินการ swap
            await swap_position_side(api_key, api_secret, symbol)
            await clear_all_orders(api_key, api_secret, symbol)

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
                message(symbol, "ไม่สามารถสร้าง Stoploss Order ได้", "red")
                state.is_swapping = False

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
                message("SYSTEM", "รอ 5 วินาทีก่อนเริ่มรอบใหม่...", "blue")
                await asyncio.sleep(5)
                
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
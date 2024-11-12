import asyncio
from datetime import datetime, timedelta
import json
import os
import traceback
import pytz
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from typing import Dict, List, Optional, Tuple

from function.binance.futures.system.create_future_exchange import create_future_exchange
from function.binance.futures.order.other.get_create_order_adjusted_price import get_adjusted_price
from function.message import message
from config import (
    TRADING_CONFIG,
    PRICE_INCREASE,
    PRICE_DECREASE,
    PRICE_CHANGE_MAXPERCENT,
    PRICE_CHANGE_THRESHOLD,
    MIN_NOTIONAL,
    api_key, api_secret
)

class BacktestPosition:
    """คลาสเก็บข้อมูล Position สำหรับ Backtest"""
    def __init__(self):
        self.entry_price = 0
        self.entry_time = None
        self.position_side = None
        self.position_size = 0
        self.leverage = 20  # Default leverage
        self.margin_type = 'cross'
        self.tp_levels_hit = {}
        self.tp_orders = {}

class BacktestState:
    """คลาสจำลองสถานะสำหรับ Backtest"""
    def __init__(self, symbol: str, config: dict):
        self.symbol = symbol
        self.config = config
        self.current_candle = None
        self.current_price = None
        self.current_stoploss = None
        self.current_rsi_period = None
        self.current_atr_length_1 = None
        self.current_atr_length_2 = None
        self.is_in_position = False
        self.is_swapping = False
        self.is_wait_candle = False
        self.position = BacktestPosition()
        self.last_candle_time = None
        self.last_candle_cross = None
        self.entry_candle = None
        self.last_focus_price = None
        self.last_focus_stopprice = None
        self.entry_candle_index = None
        self.margin_call_level = 0.5  # Margin call ที่ 50% ของ margin

    def check_margin_call(self, current_price: float) -> bool:
        """ตรวจสอบ margin call"""
        if not self.is_in_position:
            return False
            
        position_size = self.position.position_size
        entry_price = self.position.entry_price
        leverage = self.position.leverage
        
        # คำนวณมูลค่า position และ margin
        position_value = position_size * current_price
        initial_margin = (position_size * entry_price) / leverage
        
        # คำนวณ unrealized PnL
        if self.position.position_side == 'buy':
            unrealized_pnl = (current_price - entry_price) * position_size
        else:  # sell
            unrealized_pnl = (entry_price - current_price) * position_size
            
        # คำนวณ margin ratio
        current_margin = initial_margin + unrealized_pnl
        margin_ratio = current_margin / initial_margin
        
        # ถ้า margin ratio ต่ำกว่า margin_call_level ให้ margin call
        return margin_ratio <= self.margin_call_level

class BacktestTrade:
    """คลาสเก็บข้อมูลการเทรดสำหรับ Backtest"""
    def __init__(self, entry_time: datetime, entry_price: float, side: str, size: float):
        self.entry_time = entry_time
        self.entry_price = entry_price
        self.side = side
        self.size = size
        self.exit_time = None
        self.exit_price = None
        self.profit = 0
        self.profit_percent = 0
        self.reason = ''
        self.tp_hits = []
        self.sl_adjustments = []

class BacktestEngine:
    def __init__(self, symbol: str, start_date: str, end_date: str, config: dict, initial_balance: float = 1000):
        self.symbol = symbol
        self.start_date = datetime.fromisoformat(start_date)
        self.end_date = datetime.fromisoformat(end_date)
        self.config = config
        self.initial_balance = initial_balance
        self.current_balance = initial_balance
        self.state = BacktestState(symbol, config)
        self.historical_data = []
        self.trades: List[BacktestTrade] = []
        self.current_trade: Optional[BacktestTrade] = None
        self.equity_curve = []
        self.current_time = None

        """message(symbol, f"RSI Settings:", "blue")
        message(symbol, f"Oversold: {config['rsi_oversold']}", "blue")
        message(symbol, f"Overbought: {config['rsi_overbought']}", "blue")
        message(symbol, f"Period Min: {config['rsi_period']['rsi_period_min']}", "blue")
        message(symbol, f"Period Max: {config['rsi_period']['rsi_period_max']}", "blue")"""
            
        # Performance metrics
        self.metrics = {
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'total_profit': 0,
            'max_drawdown': 0,
            'win_rate': 0,
            'profit_factor': 0,
            'avg_profit_per_trade': 0,
            'largest_win': 0,
            'largest_loss': 0,
            'avg_win': 0,
            'avg_loss': 0,
            'risk_reward_ratio': 0
        }

    async def _adjust_stoploss_for_new_candle(self, df: pd.DataFrame, index: int):
        """ปรับ stoploss ตามชุด 3 แท่งเทียน"""
        if not self.state.is_in_position or index < 3:
            return
        
        # ดูย้อนหลัง 3 แท่ง
        position_side = self.state.position.position_side 
        candles = df.iloc[index-3:index]
        
        if position_side == 'buy':
            prices = [c['low'] * PRICE_DECREASE for _, c in candles.iterrows()]
            # หาราคาที่สูงขึ้นเรื่อยๆ 
            if prices[2] > prices[1] > prices[0]:
                new_stoploss = prices[0]
                if new_stoploss > self.state.current_stoploss:
                    self.state.current_stoploss = new_stoploss
        else:
            prices = [c['high'] * PRICE_INCREASE for _, c in candles.iterrows()]
            # หาราคาที่ต่ำลงเรื่อยๆ
            if prices[2] < prices[1] < prices[0]:
                new_stoploss = prices[0] 
                if new_stoploss < self.state.current_stoploss:
                    self.state.current_stoploss = new_stoploss

    async def _adjust_tp_orders(self, df: pd.DataFrame, index: int):
        """ปรับ TP Orders หลังผ่าน 2 แท่ง"""
        if not self.state.is_in_position or not self.state.entry_candle_index:
            return
            
        # หาจำนวนแท่งที่ผ่านไปหลัง entry
        current_timestamp = df.iloc[index]['timestamp'].timestamp() * 1000
        entry_timestamp = self.state.entry_candle_index
        candles_passed = sum(1 for i in range(index) if df.iloc[i]['timestamp'].timestamp() * 1000 > entry_timestamp)
        
        if candles_passed < 2:  # ยังไม่ผ่าน 2 แท่ง
            return
            
        position_side = self.state.position.position_side
        atr = self.state.current_atr_length_2
        
        # คำนวณราคาอ้างอิงใหม่
        if position_side == 'buy':
            ref_price = max(df.iloc[index-1]['high'], self.state.position.entry_price)
        else:
            ref_price = min(df.iloc[index-1]['low'], self.state.position.entry_price)
            
        # ปรับ TP ใหม่ตามราคาอ้างอิง
        for level in self.config['take_profits']['levels']:
            if not self.state.position.tp_levels_hit.get(level['id'], False):
                if position_side == 'buy':
                    tp_price = ref_price + (atr * level['target_atr'])
                else:
                    tp_price = ref_price - (atr * level['target_atr'])
                # บันทึก TP ใหม่
                if not hasattr(self.state.position, 'tp_orders'):
                    self.state.position.tp_orders = {}
                self.state.position.tp_orders[level['id']] = tp_price

    def _calculate_current_equity(self) -> float:
        """คำนวณ equity ปัจจุบัน"""
        if not self.state.is_in_position:
            return self.current_balance
            
        # คำนวณ unrealized P&L
        position_side = self.state.position.position_side
        entry_price = self.state.position.entry_price
        position_size = self.state.position.position_size
        current_price = self.state.current_price
        
        if position_side == 'buy':
            unrealized_pnl = (current_price - entry_price) * position_size
        else:
            unrealized_pnl = (entry_price - current_price) * position_size
            
        return self.current_balance + unrealized_pnl

    def _is_tp_hit(self, tp_price: float, position_side: str, candle: dict) -> bool:
        """ตรวจสอบว่า TP โดนหรือไม่"""
        if position_side == 'buy':
            return candle['high'] >= tp_price
        else:  # sell
            return candle['low'] <= tp_price

    def _calculate_tp_price(self, entry_price: float, level: dict, position_side: str) -> float:
        """คำนวณราคา Take Profit"""
        atr = self.state.current_atr_length_2
        target_atr = level['target_atr']
        
        if position_side == 'buy':
            tp_base = entry_price + (atr * target_atr)
            return tp_base * (PRICE_INCREASE + (PRICE_CHANGE_THRESHOLD * (target_atr * 2)))
        else:
            tp_base = entry_price - (atr * target_atr)
            return tp_base * (PRICE_DECREASE - (PRICE_CHANGE_THRESHOLD * (target_atr * 2)))

    async def _should_swap_position(self, df: pd.DataFrame, index: int) -> bool:
        """ตรวจสอบเงื่อนไขการ Swap Position"""
        if not self.state.last_focus_price:
            return False
            
        current_candle = self.state.current_candle
        position_side = self.state.position.position_side
        
        if position_side == 'buy':
            return current_candle['low'] < self.state.last_focus_price * PRICE_DECREASE
        else:  # sell
            return current_candle['high'] > self.state.last_focus_price * PRICE_INCREASE

    async def _simulate_position_swap(self, candle: dict):
        """จำลองการ Swap Position"""
        old_side = self.state.position.position_side
        old_entry_price = self.state.position.entry_price
        current_price = candle['close']
        
        # บันทึกการปิด Position เดิม
        await self._simulate_position_close(
            current_price,
            f'Swap from {old_side}',
            candle['timestamp']
        )
        
        # เข้า Position ใหม่
        new_side = 'buy' if old_side == 'sell' else 'sell'
        focus_candle = self.state.last_candle_cross['candle']
        
        if new_side == 'buy':
            new_stoploss = float(focus_candle['low']) * PRICE_DECREASE
        else:
            new_stoploss = float(focus_candle['high']) * PRICE_INCREASE
            
        position_size = self._calculate_position_size(
            current_price,
            new_stoploss,
            self.config['entry_amount']
        )
        
        # สร้าง Trade ใหม่
        self.current_trade = BacktestTrade(
            self.current_time,
            current_price,
            new_side,
            position_size
        )
        
        # อัพเดทสถานะ
        self.state.is_in_position = True
        self.state.position = BacktestPosition()
        self.state.position.entry_price = current_price
        self.state.position.entry_time = self.current_time
        self.state.position.position_side = new_side
        self.state.position.position_size = position_size
        self.state.current_stoploss = new_stoploss
        self.state.entry_candle = candle.copy()
        self.state.is_swapping = False
        self.state.last_focus_price = None
    async def load_historical_data(self):
        """โหลดข้อมูลราคาย้อนหลัง"""
        exchange = await create_future_exchange(api_key, api_secret)
        try:
            # แปลง timeframe เป็น milliseconds
            timeframe = self.config['timeframe']
            if timeframe.endswith('h'):
                ms_per_candle = int(timeframe[:-1]) * 60 * 60 * 1000
            elif timeframe.endswith('m'):
                ms_per_candle = int(timeframe[:-1]) * 60 * 1000
            elif timeframe.endswith('d'):
                ms_per_candle = int(timeframe[:-1]) * 24 * 60 * 60 * 1000
            
            # คำนวณจำนวนแท่งเทียนที่ต้องการ
            total_ms = (self.end_date - self.start_date).total_seconds() * 1000
            num_candles = int(total_ms / ms_per_candle) + 100  # เผื่อแท่งเพิ่มสำหรับ indicators
            
            # โหลดข้อมูลแบบแบ่งช่วง
            since = int(self.start_date.timestamp() * 1000)
            all_candles = []
            
            while len(all_candles) < num_candles:
                candles = await exchange.fetch_ohlcv(
                    self.symbol, 
                    timeframe,
                    since=since,
                    limit=1000
                )
                if not candles:
                    break
                    
                all_candles.extend(candles)
                since = candles[-1][0] + ms_per_candle
                
                # รอสักครู่เพื่อไม่ให้เกิน rate limit
                await asyncio.sleep(0.1)
            
            self.historical_data = all_candles
            message(self.symbol, f"โหลดข้อมูลทั้งหมด {len(all_candles)} แท่ง", "blue")
            
        finally:
            await exchange.close()

    def _calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """คำนวณ indicators ทั้งหมด"""
        # คำนวณ ATR
        def calculate_atr(high, low, close, length):
            tr = np.maximum(
                high - low,
                np.maximum(
                    np.abs(high - close.shift(1)),
                    np.abs(low - close.shift(1))
                )
            )
            return tr.ewm(alpha=1/length, adjust=False).mean()
        
        # ATR สำหรับ period ต่างๆ
        df['atr_length1'] = calculate_atr(
            df['high'], df['low'], df['close'],
            self.config['rsi_period']['atr']['length1']
        )
        df['atr_length2'] = calculate_atr(
            df['high'], df['low'], df['close'],
            self.config['rsi_period']['atr']['length2']
        )
        
        # คำนวณ RSI period แบบไดนามิก
        def get_dynamic_rsi_period(row):
            """คำนวณ RSI Period แบบไดนามิก"""
            try:
                # ถ้ามีค่า NaN ในการคำนวณให้ใช้ค่า min
                if pd.isna(row['atr_length1']) or pd.isna(row['atr_length2']):
                    return self.config['rsi_period']['rsi_period_min']
                    
                if not self.config['rsi_period'].get('use_dynamic_period', True):
                    return self.config['rsi_period']['rsi_period_min']
                        
                # คำนวณเปอร์เซ็นต์ความต่างของ ATR
                atr_diff_percent = ((row['atr_length1'] - row['atr_length2']) / row['atr_length2']) * 100
                        
                if atr_diff_percent >= self.config['rsi_period']['atr']['max_percent']:
                    return self.config['rsi_period']['rsi_period_max']
                elif atr_diff_percent <= self.config['rsi_period']['atr']['min_percent']:
                    return self.config['rsi_period']['rsi_period_min']
                else:
                    period_range = (
                        self.config['rsi_period']['rsi_period_max'] - 
                        self.config['rsi_period']['rsi_period_min']
                    )
                    volatility_range = (
                        self.config['rsi_period']['atr']['max_percent'] - 
                        self.config['rsi_period']['atr']['min_percent']
                    )
                    period_step = (
                        (atr_diff_percent - self.config['rsi_period']['atr']['min_percent']) / 
                        volatility_range
                    )
                    value = self.config['rsi_period']['rsi_period_min'] + (period_range * period_step)
                    return int(round(value))
                    
            except Exception as e:
                # ถ้ามีข้อผิดพลาดใดๆ ให้ใช้ค่า min
                return self.config['rsi_period']['rsi_period_min']
        
        df['rsi_period'] = df.apply(get_dynamic_rsi_period, axis=1)
        
        # คำนวณ RSI แบบไดนามิก
        def calculate_dynamic_rsi(data):
            """คำนวณ RSI แบบไดนามิก"""
            close_diff = data['close'].diff()
            gains = close_diff.where(close_diff > 0, 0)
            losses = -close_diff.where(close_diff < 0, 0)
            
            rsi_values = []
            current_period = data['rsi_period'].iloc[0]
            
            #message(self.symbol, f"Using RSI Period: {current_period}", "blue")
            
            # คำนวณค่าเฉลี่ยเริ่มต้น
            avg_gain = gains.rolling(window=current_period).mean().iloc[current_period-1]
            avg_loss = losses.rolling(window=current_period).mean().iloc[current_period-1]
            
            for i in range(len(data)):
                if i < current_period:
                    rsi_values.append(np.nan)
                    continue
                    
                current_gain = gains.iloc[i]
                current_loss = losses.iloc[i]
                
                avg_gain = ((avg_gain * (current_period - 1)) + current_gain) / current_period
                avg_loss = ((avg_loss * (current_period - 1)) + current_loss) / current_period
                
                if avg_loss == 0:
                    rsi = 100
                else:
                    rs = avg_gain / avg_loss
                    rsi = 100 - (100 / (1 + rs))
                
                rsi_values.append(rsi)
                
                # Log ทุก 100 แท่ง
                """if i % 100 == 0:
                    message(self.symbol, f"RSI at candle {i}: {rsi:.2f}", "blue")"""
            
            return pd.Series(rsi_values, index=data.index)

        # เพิ่ม RSI column
        df['rsi'] = calculate_dynamic_rsi(df)

        # ส่งคืน DataFrame ที่มีการคำนวณ indicators เรียบร้อยแล้ว
        return df

    async def run_backtest(self):
        """รัน backtest"""
        await self.load_historical_data()
        
        # แปลงข้อมูลเป็น DataFrame
        df = pd.DataFrame(
            self.historical_data,
            columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
        )
        
        # แปลง timestamp เป็น datetime
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        
        # คำนวณ indicators
        df = self._calculate_indicators(df)
        
        # วนลูปผ่านแต่ละแท่งเทียน
        for i in range(len(df)):
            current_row = df.iloc[i]
            self.current_time = current_row['timestamp']
            
            # อัพเดทข้อมูลตลาดจำลอง
            self.state.current_candle = {
                'timestamp': int(current_row['timestamp'].timestamp() * 1000),
                'open': current_row['open'],
                'high': current_row['high'],
                'low': current_row['low'],
                'close': current_row['close'],
                'volume': current_row['volume']
            }
            self.state.current_price = current_row['close']
            
            # อัพเดท indicators
            self.state.current_atr_length_1 = current_row['atr_length1']
            self.state.current_atr_length_2 = current_row['atr_length2']
            self.state.current_rsi_period = current_row['rsi_period']
            
            # จำลองการทำงานของระบบ
            await self._simulate_trading_logic(df, i)
            
            # บันทึก equity curve
            current_equity = self._calculate_current_equity()
            self.equity_curve.append({
                'timestamp': self.current_time,
                'equity': current_equity
            })
            
        # คำนวณ metrics เมื่อจบ backtest
        self._calculate_performance_metrics()

    async def _simulate_trading_logic(self, df: pd.DataFrame, index: int):
        """จำลองการทำงานของระบบเทรด"""
        try:
            current_candle = self.state.current_candle
            backtest_config = BacktestConfig()
            
            # Log ค่า RSI และ indicators
            #message(self.symbol, f"Candle {index} - RSI: {df['rsi'].iloc[index]:.2f}, ATR1: {df['atr_length1'].iloc[index]:.8f}, ATR2: {df['atr_length2'].iloc[index]:.8f}", "blue")
            
            # จัดการ Position ที่มีอยู่
            if self.state.is_in_position:
                position_side = self.state.position.position_side
                entry_price = self.state.position.entry_price
                position_size = self.state.position.position_size
                current_price = current_candle['close']
                
                # 1. ตรวจสอบ Margin Call
                if self.state.check_margin_call(current_price):
                    message(self.symbol, f"Margin Call at price {current_price:.8f}!", "red")
                    exit_price = backtest_config.calculate_execution_price(
                        current_price, 
                        'sell' if position_side == 'buy' else 'buy', 
                        'MARKET'
                    )
                    fee = backtest_config.calculate_fee(position_size, exit_price, False)
                    await self._simulate_position_close(
                        exit_price,
                        'Margin Call',
                        current_candle['timestamp']
                    )
                    self.current_balance -= fee
                    return
                
                # 2. ปรับ Stoploss ตามชุด 3 แท่งเทียน
                if index >= 3:  # ต้องมีแท่งเทียนพอ
                    old_stoploss = self.state.current_stoploss
                    await self._adjust_stoploss_for_new_candle(df, index)
                    if old_stoploss != self.state.current_stoploss:
                        message(self.symbol, f"Stoploss adjusted from {old_stoploss:.8f} to {self.state.current_stoploss:.8f}", "cyan")
                
                # 3. ตรวจสอบ Stoploss Hit
                if self.state.current_stoploss:
                    if position_side == 'buy' and current_candle['low'] <= self.state.current_stoploss:
                        message(self.symbol, f"Stoploss Hit at {self.state.current_stoploss:.8f}", "yellow")
                        exit_price = backtest_config.calculate_execution_price(
                            self.state.current_stoploss, 'sell', 'MARKET')
                        fee = backtest_config.calculate_fee(position_size, exit_price, False)
                        await self._simulate_position_close(
                            exit_price,
                            'Stoploss Hit',
                            current_candle['timestamp']
                        )
                        self.current_balance -= fee
                        return
                    elif position_side == 'sell' and current_candle['high'] >= self.state.current_stoploss:
                        message(self.symbol, f"Stoploss Hit at {self.state.current_stoploss:.8f}", "yellow")
                        exit_price = backtest_config.calculate_execution_price(
                            self.state.current_stoploss, 'buy', 'MARKET')
                        fee = backtest_config.calculate_fee(position_size, exit_price, False)
                        await self._simulate_position_close(
                            exit_price,
                            'Stoploss Hit',
                            current_candle['timestamp']
                        )
                        self.current_balance -= fee
                        return
                
                # 4. ตรวจสอบและปรับ TP Orders
                if not self.state.is_swapping:
                    # ปรับ TP หลังผ่าน 2 แท่ง
                    await self._adjust_tp_orders(df, index)
                    
                    # ตรวจสอบ TP Hit
                    for level in self.config['take_profits']['levels']:
                        if not self.state.position.tp_levels_hit.get(level['id'], False):
                            tp_price = self._calculate_tp_price(entry_price, level, position_side)
                            if self._is_tp_hit(tp_price, position_side, current_candle):
                                message(self.symbol, f"Take Profit {level['id']} Hit at {tp_price:.8f}", "green")
                                exit_price = backtest_config.calculate_execution_price(
                                    tp_price, 'sell' if position_side == 'buy' else 'buy', 'LIMIT')
                                fee = backtest_config.calculate_fee(position_size, exit_price, True)
                                await self._simulate_tp_hit(level, tp_price, current_candle['timestamp'])
                                self.current_balance -= fee
                                
                                # ถ้าเป็น TP สุดท้ายหรือ MAX size ให้ปิด position
                                if level.get('size', '') == 'MAX' or level['id'] == f"tp{len(self.config['take_profits']['levels'])}":
                                    await self._simulate_position_close(
                                        exit_price,
                                        f'Take Profit {level["id"]} Hit (Complete)',
                                        current_candle['timestamp']
                                    )
                                    return
                
                # 5. ตรวจสอบ Focus Price Break
                if self.state.last_focus_price:
                    if position_side == 'buy':
                        if current_candle['high'] > self.state.last_focus_price * PRICE_INCREASE:
                            message(self.symbol, f"Focus Price Break UP at {current_candle['high']:.8f}", "cyan")
                            await self._simulate_focus_price_break('buy')
                    elif position_side == 'sell':
                        if current_candle['low'] < self.state.last_focus_price * PRICE_DECREASE:
                            message(self.symbol, f"Focus Price Break DOWN at {current_candle['low']:.8f}", "cyan")
                            await self._simulate_focus_price_break('sell')
                
                # 6. ตรวจสอบ Swap Position
                if self.state.last_candle_cross and not self.state.is_swapping:
                    should_swap = await self._should_swap_position(df, index)
                    if should_swap:
                        message(self.symbol, f"Swapping Position from {position_side}", "magenta")
                        await self._simulate_position_swap(current_candle)
            
            # ตรวจสอบสัญญาณเข้าใหม่
            else:
                signal = self._check_entry_signal(df, index)
                if signal:
                    message(self.symbol, f"Entry Signal: {signal['type']} (RSI: {df['rsi'].iloc[index]:.2f})", "yellow")
                    await self._simulate_entry(signal, current_candle)
                    
                    # Log entry details
                    message(self.symbol, f"Entry Price: {self.state.position.entry_price:.8f}", "yellow")
                    message(self.symbol, f"Position Size: {self.state.position.position_size:.8f}", "yellow")
                    message(self.symbol, f"Stoploss: {self.state.current_stoploss:.8f}", "yellow")
                    
                    # Log take profit levels
                    for level in self.config['take_profits']['levels']:
                        tp_price = self._calculate_tp_price(
                            self.state.position.entry_price,
                            level,
                            self.state.position.position_side
                        )
                        message(self.symbol, f"TP {level['id']}: {tp_price:.8f}", "yellow")

        except Exception as e:
            import traceback
            error_traceback = traceback.format_exc()
            message(self.symbol, f"Backtest Error: {str(e)}", "red")
            message(self.symbol, f"Error Traceback: {error_traceback}", "red")

    def _check_entry_signal(self, df: pd.DataFrame, index: int) -> Optional[dict]:
        """ตรวจสอบสัญญาณเข้า"""
        if index < 2:
            return None
                
        current_rsi = df['rsi'].iloc[index]
        prev_rsi = df['rsi'].iloc[index-1]
        
        # เพิ่ม logging เพื่อ debug
        #message(self.symbol, f"RSI Values - Current: {current_rsi:.2f}, Previous: {prev_rsi:.2f}", "blue")
        
        result = {
            'status': False,
            'type': None,
            'rsi_period_used': self.state.current_rsi_period,
            'candle': self.state.current_candle
        }
        
        # ปรับปรุงเงื่อนไขการตรวจจับ crossover/crossunder
        if prev_rsi > self.config['rsi_overbought'] and current_rsi <= self.config['rsi_overbought']:
            result['status'] = True
            result['type'] = 'crossunder'
            #message(self.symbol, f"Found SELL Signal - RSI crossed below {self.config['rsi_overbought']}", "yellow")
        elif prev_rsi < self.config['rsi_oversold'] and current_rsi >= self.config['rsi_oversold']:
            result['status'] = True
            result['type'] = 'crossover'
            #message(self.symbol, f"Found BUY Signal - RSI crossed above {self.config['rsi_oversold']}", "yellow")
        
        return result if result['status'] else None

    async def _simulate_entry(self, signal: dict, candle: dict):
        """จำลองการเข้า Position"""
        if signal['type'] == 'crossover':
            entry_price = float(candle['high']) * PRICE_INCREASE
            stoploss_price = float(candle['low']) * PRICE_DECREASE
            position_side = 'buy'
        else:  # crossunder
            entry_price = float(candle['low']) * PRICE_DECREASE
            stoploss_price = float(candle['high']) * PRICE_INCREASE
            position_side = 'sell'
        
        # คำนวณ position size
        position_size = self._calculate_position_size(
            entry_price,
            stoploss_price,
            self.config['entry_amount']
        )
        
        # บันทึก trade ใหม่
        self.current_trade = BacktestTrade(
            self.current_time,
            entry_price,
            position_side,
            position_size
        )
        
        # อัพเดทสถานะ
        self.state.is_in_position = True
        self.state.position = BacktestPosition()
        self.state.position.entry_price = entry_price
        self.state.position.entry_time = self.current_time
        self.state.position.position_side = position_side
        self.state.position.position_size = position_size
        self.state.current_stoploss = stoploss_price
        self.state.entry_candle = candle.copy()
        # เก็บ timestamp แทนการใช้ index
        self.state.entry_candle_index = candle['timestamp']

    async def _simulate_position_close(self, exit_price: float, reason: str, timestamp: int):
        """จำลองการปิด Position"""
        if not self.state.is_in_position:
            return
            
        # คำนวณกำไร/ขาดทุน
        position_side = self.state.position.position_side
        entry_price = self.state.position.entry_price
        position_size = self.state.position.position_size
        
        if position_side == 'buy':
            profit = (exit_price - entry_price) * position_size
        else:
            profit = (entry_price - exit_price) * position_size
            
        # อัพเดท trade ปัจจุบัน
        if self.current_trade:
            self.current_trade.exit_time = self.current_time
            self.current_trade.exit_price = exit_price
            self.current_trade.profit = profit
            self.current_trade.profit_percent = (profit / (entry_price * position_size)) * 100
            self.current_trade.reason = reason
            self.trades.append(self.current_trade)
            self.current_trade = None
        
        # อัพเดทเงินทุน
        self.current_balance += profit
        
        # รีเซ็ตสถานะ
        self.state.is_in_position = False
        self.state.position = BacktestPosition()
        self.state.current_stoploss = None
        self.state.last_focus_price = None
        self.state.last_focus_stopprice = None
        self.state.is_wait_candle = False
        self.state.last_candle_cross = None

    async def _simulate_tp_hit(self, level: dict, tp_price: float, timestamp: int):
        """จำลองการโดน Take Profit"""
        # บันทึกว่า TP level นี้ถูก hit แล้ว
        self.state.position.tp_levels_hit[level['id']] = True
        
        # ถ้าเป็น TP1 และต้องย้าย SL ไปจุดเข้า
        if level['id'] == 'tp1' and self.config['take_profits'].get('move_sl_to_entry_at_tp1', True):
            entry_price = self.state.position.entry_price
            position_side = self.state.position.position_side
            
            if position_side == 'buy':
                self.state.current_stoploss = entry_price * (PRICE_DECREASE - PRICE_CHANGE_THRESHOLD)
            else:
                self.state.current_stoploss = entry_price * (PRICE_INCREASE + PRICE_CHANGE_THRESHOLD)
                
        # บันทึก TP hit ในประวัติการเทรด
        if self.current_trade:
            self.current_trade.tp_hits.append({
                'level': level['id'],
                'price': tp_price,
                'time': self.current_time
            })

    async def _simulate_focus_price_break(self, side: str):
        """จำลองการทะลุ Focus Price"""
        current_candle = self.state.current_candle
        focus_candle = self.state.last_candle_cross['candle']
        
        if side == 'buy':
            # เลือก stoploss ที่เหมาะสม
            focus_low = float(focus_candle['low'])
            current_low = float(current_candle['low'])
            new_stoploss = (focus_low if focus_low < current_low else current_low) * PRICE_DECREASE
        else:
            # เลือก stoploss ที่เหมาะสม
            focus_high = float(focus_candle['high'])
            current_high = float(current_candle['high'])
            new_stoploss = (focus_high if focus_high > current_high else current_high) * PRICE_INCREASE
        
        # บันทึกการปรับ stoploss
        if self.current_trade:
            self.current_trade.sl_adjustments.append({
                'from': self.state.current_stoploss,
                'to': new_stoploss,
                'time': self.current_time,
                'reason': 'Focus Price Break'
            })
        
        self.state.current_stoploss = new_stoploss
        self.state.is_wait_candle = False

    def _calculate_position_size(self, entry_price: float, stoploss_price: float, amount: str) -> float:
        """คำนวณขนาด Position"""
        # แปลงจำนวนเงินจากสตริง (เช่น "50$") เป็นตัวเลข
        if amount.endswith('$'):
            amount = float(amount[:-1])
        else:
            amount = float(amount)
            
        # คำนวณเปอร์เซ็นต์ความเสี่ยง
        risk_percent = abs((entry_price - stoploss_price) / entry_price * 100)
        
        # ปรับ quantity ตาม stoploss
        if self.config.get('fix_stoploss'):
            target_percent = float(self.config['fix_stoploss'])
            adjustment_ratio = target_percent / risk_percent
            amount = amount * adjustment_ratio
            
        # ตรวจสอบ minimum notional
        if amount * entry_price < MIN_NOTIONAL:
            amount = MIN_NOTIONAL / entry_price
            
        return amount

    def _calculate_performance_metrics(self):
        """คำนวณ metrics ต่างๆ"""
        if not self.trades:
            return
            
        # ข้อมูลพื้นฐาน
        self.metrics['total_trades'] = len(self.trades)
        self.metrics['winning_trades'] = len([t for t in self.trades if t.profit > 0])
        self.metrics['losing_trades'] = len([t for t in self.trades if t.profit < 0])
        
        # กำไร/ขาดทุน
        self.metrics['total_profit'] = sum(t.profit for t in self.trades)
        self.metrics['largest_win'] = max(t.profit for t in self.trades)
        self.metrics['largest_loss'] = min(t.profit for t in self.trades)
        
        winning_trades = [t for t in self.trades if t.profit > 0]
        losing_trades = [t for t in self.trades if t.profit < 0]
        
        if winning_trades:
            self.metrics['avg_win'] = sum(t.profit for t in winning_trades) / len(winning_trades)
        if losing_trades:
            self.metrics['avg_loss'] = sum(t.profit for t in losing_trades) / len(losing_trades)
            
        # อัตราส่วนต่างๆ
        self.metrics['win_rate'] = self.metrics['winning_trades'] / self.metrics['total_trades']
        
        total_gains = sum(t.profit for t in self.trades if t.profit > 0)
        total_losses = abs(sum(t.profit for t in self.trades if t.profit < 0))
        if total_losses > 0:
            self.metrics['profit_factor'] = total_gains / total_losses
            
        if self.metrics['avg_loss'] != 0:
            self.metrics['risk_reward_ratio'] = abs(self.metrics['avg_win'] / self.metrics['avg_loss'])
            
        # Maximum Drawdown
        equity_curve = pd.DataFrame(self.equity_curve)
        rolling_max = equity_curve['equity'].expanding().max()
        drawdown = (equity_curve['equity'] - rolling_max) / rolling_max * 100
        self.metrics['max_drawdown'] = abs(drawdown.min())

    def plot_results(self):
        """สร้างกราฟแสดงผลการ backtest"""
        # สร้าง subplot
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(15, 12))
        
        # 1. กราฟราคาและจุดเทรด
        df = pd.DataFrame(self.historical_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        
        ax1.plot(df['timestamp'], df['close'], label='Price')
        
        # พล็อตจุด Entry/Exit
        for trade in self.trades:
            if trade.side == 'buy':
                ax1.scatter(trade.entry_time, trade.entry_price, color='g', marker='^', s=100)
                ax1.scatter(trade.exit_time, trade.exit_price, color='r', marker='v', s=100)
            else:
                ax1.scatter(trade.entry_time, trade.entry_price, color='r', marker='v', s=100)
                ax1.scatter(trade.exit_time, trade.exit_price, color='g', marker='^', s=100)
        
        ax1.set_title('Price Chart with Entry/Exit Points')
        ax1.legend()
        
        # 2. Equity Curve
        equity_df = pd.DataFrame(self.equity_curve)
        ax2.plot(equity_df['timestamp'], equity_df['equity'])
        ax2.set_title('Equity Curve')
        
        # 3. Drawdown
        rolling_max = equity_df['equity'].expanding().max()
        drawdown = (equity_df['equity'] - rolling_max) / rolling_max * 100
        ax3.fill_between(equity_df['timestamp'], drawdown, 0, color='red', alpha=0.3)
        ax3.set_title('Drawdown')
        
        plt.tight_layout()
        plt.show()

    def generate_report(self) -> str:
        """สร้างรายงานผลการ backtest"""
        report = [
            f"Backtest Report for {self.symbol}",
            f"Period: {self.start_date.date()} to {self.end_date.date()}",
            "",
            "Performance Metrics:",
            f"Total Trades: {self.metrics['total_trades']}",
            f"Winning Trades: {self.metrics['winning_trades']}",
            f"Losing Trades: {self.metrics['losing_trades']}",
            f"Win Rate: {self.metrics['win_rate']:.2%}",
            f"Total Profit: ${self.metrics['total_profit']:.2f}",
            f"Profit Factor: {self.metrics['profit_factor']:.2f}",
            f"Risk Reward Ratio: {self.metrics['risk_reward_ratio']:.2f}",
            f"Maximum Drawdown: {self.metrics['max_drawdown']:.2%}",
            "",
            "Trade Statistics:",
            f"Average Win: ${self.metrics['avg_win']:.2f}",
            f"Average Loss: ${self.metrics['avg_loss']:.2f}",
            f"Largest Win: ${self.metrics['largest_win']:.2f}",
            f"Largest Loss: ${self.metrics['largest_loss']:.2f}",
            "",
            "Trading System Settings:",
            f"Initial Balance: ${self.initial_balance:.2f}",
            f"Final Balance: ${self.current_balance:.2f}",
            f"Total Return: {((self.current_balance/self.initial_balance)-1)*100:.2f}%"
        ]
        
        return "\n".join(report)

async def run_backtest_analysis():
    """ฟังก์ชันหลักสำหรับรัน backtest"""
    # โหลด config จาก index.json
    if not os.path.exists('json/index.json'):
        message("SYSTEM", "ไม่พบไฟล์ index.json", "red")
        return
        
    with open('json/index.json', 'r') as f:
        configs = json.load(f)
    
    results = []
    
    # รัน backtest สำหรับแต่ละเหรียญ
    for config in configs:
        symbol = config['symbol']
        message("SYSTEM", f"เริ่ม Backtest {symbol}", "blue")
        
        engine = BacktestEngine(
            symbol=symbol,
            start_date="2023-01-01",
            end_date="2024-11-09",
            config=config,
            initial_balance=1000
        )
        
        await engine.run_backtest()
        
        # สร้างรายงานและกราฟ
        report = engine.generate_report()
        print(report)
        engine.plot_results()
        
        results.append({
            'symbol': symbol,
            'metrics': engine.metrics,
            'trades': len(engine.trades)
        })
        
        message("SYSTEM", f"เสร็จสิ้น Backtest {symbol}", "green")
    
    return results

class BacktestConfig:
    def __init__(self):
        self.maker_fee = 0.0002  # 0.02%
        self.taker_fee = 0.0004  # 0.04% 
        self.slippage = 0.0005   # 0.05%

    def calculate_execution_price(self, price: float, side: str, order_type: str) -> float:
        """คำนวณราคาที่ทำได้จริงรวม slippage"""
        if order_type == 'MARKET':
            slippage_factor = 1 + (self.slippage if side == 'buy' else -self.slippage)
            return price * slippage_factor
        return price

    def calculate_fee(self, amount: float, price: float, is_maker: bool) -> float:
        """คำนวณค่าธรรมเนียม"""
        fee_rate = self.maker_fee if is_maker else self.taker_fee
        return amount * price * fee_rate

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    results = loop.run_until_complete(run_backtest_analysis())
    loop.close()
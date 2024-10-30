import traceback
import ccxt.async_support as ccxt
import pandas as pd
import numpy as np
from datetime import datetime
import pytz

from function.binance.futures.order.other.get_kline_data import fetch_ohlcv
from function.binance.futures.system.create_future_exchange import create_future_exchange
from function.message import message

def calculate_rsi(close_prices, length):
    if len(close_prices) < length + 1:
        return np.zeros_like(close_prices)
        
    deltas = np.diff(close_prices)
    seed = deltas[:length+1]
    up = seed[seed >= 0].sum()/length
    down = -seed[seed < 0].sum()/length
    
    # ป้องกันการหารด้วย 0
    if down == 0:
        if up == 0:
            rs = 1.0  # ถ้าทั้ง up และ down เป็น 0
        else:
            rs = float('inf')  # ถ้าเฉพาะ down เป็น 0
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
        
        # ป้องกันการหารด้วย 0
        if down == 0:
            if up == 0:
                rs = 1.0
            else:
                rs = float('inf')
        else:
            rs = up/down
            
        rsi[i] = 100. - 100./(1. + rs)

    # ทำให้แน่ใจว่าค่า RSI อยู่ในช่วง 0-100
    rsi = np.clip(rsi, 0, 100)
    return rsi

async def get_rsi_cross_last_candle(api_key, api_secret, symbol, timeframe, rsi_length, oversold, overbought, candle_index=0):
    exchange = await create_future_exchange(api_key, api_secret)
    
    try:
        # ดึงข้อมูลมากขึ้นเพื่อให้แน่ใจว่ามีข้อมูลพอ
        ohlcv = await fetch_ohlcv(symbol, timeframe, limit=100)  # เพิ่มจาก 100 เป็น 200
        
        if not ohlcv or len(ohlcv) < rsi_length + 10:  # ตรวจสอบว่ามีข้อมูลพอ
            return {
                'status': False,
                'type': None,
                'candle': None,
                'error': 'ข้อมูลไม่เพียงพอสำหรับการคำนวณ RSI'
            }
            
        await exchange.close()
        
        # ตัดแท่งเทียนปัจจุบันออก
        closed_ohlcv = ohlcv[:-1]
        
        # แปลงเป็น DataFrame
        df = pd.DataFrame(closed_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # แปลงเวลา UTC เป็นเวลาท้องถิ่น
        local_tz = pytz.timezone('Asia/Bangkok')
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms').dt.tz_localize(pytz.UTC).dt.tz_convert(local_tz)
        
        # คำนวณ RSI
        with np.errstate(divide='ignore', invalid='ignore'):  # ป้องกัน warnings
            df['rsi'] = calculate_rsi(df['close'].values, rsi_length)
        
        # ตรวจสอบว่ามีข้อมูลพอสำหรับการเช็ค crossover
        if len(df) < 2 + candle_index:  # ปรับจาก 3 เป็น 2 เพราะตัดแท่งปัจจุบันออกแล้ว
            return {
                'status': False,
                'type': None,
                'candle': None,
                'error': 'ข้อมูลไม่เพียงพอสำหรับการตรวจสอบ crossover'
            }
            
        # เช็ค crossover/crossunder จากแท่งที่ปิดแล้ว
        last_closed_rsi = df['rsi'].iloc[-(1 + candle_index)]  # ปรับ index เพราะตัดแท่งปัจจุบันออกแล้ว
        prev_closed_rsi = df['rsi'].iloc[-(2 + candle_index)]
        
        # ตรวจสอบค่า NaN
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
            'candle': {
                'open': float(df['open'].iloc[-(1 + candle_index)]),  # ปรับ index
                'high': float(df['high'].iloc[-(1 + candle_index)]),
                'low': float(df['low'].iloc[-(1 + candle_index)]),
                'close': float(df['close'].iloc[-(1 + candle_index)]),
                'volume': float(df['volume'].iloc[-(1 + candle_index)]),
                'timestamp': int(df['timestamp'].iloc[-(1 + candle_index)].timestamp() * 1000),  # เพิ่ม timestamp
                'time': df['timestamp'].iloc[-(1 + candle_index)].strftime('%d/%m/%Y %H:%M'),
                'rsi': round(float(last_closed_rsi), 2)
            }
        }
        
        # ตรวจสอบเงื่อนไข crossover/crossunder
        if prev_closed_rsi >= overbought and last_closed_rsi < overbought:
            result['status'] = True
            result['type'] = 'crossunder'
        elif prev_closed_rsi <= oversold and last_closed_rsi > oversold:
            result['status'] = True
            result['type'] = 'crossover'
        elif prev_closed_rsi < overbought and last_closed_rsi >= overbought:
            result['status'] = True
            result['type'] = 'crossover'
        elif prev_closed_rsi > oversold and last_closed_rsi <= oversold:
            result['status'] = True
            result['type'] = 'crossunder'
        
        return result

    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"เกิดข้อผิดพลาดในการคำนวณ RSI: {str(e)}", "red")
        message(symbol, f"Error: {error_traceback}", "red")
        return None
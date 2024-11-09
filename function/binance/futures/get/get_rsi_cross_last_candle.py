# import traceback
# import ccxt.async_support as ccxt
# import pandas as pd
# import numpy as np
# from datetime import datetime
# import pytz

# from function.binance.futures.order.other.get_kline_data import fetch_ohlcv
# from function.binance.futures.system.create_future_exchange import create_future_exchange
# from function.message import message

# async def calculate_atr(api_key, api_secret, symbol, timeframe, state: SymbolState, length=7):
#     """คำนวณค่า ATR (Average True Range)"""
#     try:
#         if timeframe not in state.current_market_data.get('atr_cache', {}):
#             exchange = await create_future_exchange(api_key, api_secret)
#             ohlcv = await fetch_ohlcv(symbol, timeframe, limit=length + 1)
            
#             if len(ohlcv) < length + 1:
#                 message(symbol, f"ข้อมูลไม่พอสำหรับคำนวณ ATR (ต้องการ {length + 1} แท่ง)", "yellow")
#                 return None

#             tr_values = []
#             for i in range(1, len(ohlcv)):
#                 high = ohlcv[i][2]
#                 low = ohlcv[i][3]
#                 prev_close = ohlcv[i-1][4]
                
#                 tr = max(
#                     high - low,
#                     abs(high - prev_close),
#                     abs(low - prev_close)
#                 )
#                 tr_values.append(tr)

#             alpha = 1.0 / length
#             rma = tr_values[0]
#             for tr in tr_values[1:]:
#                 rma = (alpha * tr) + ((1 - alpha) * rma)

#             if 'atr_cache' not in state.current_market_data:
#                 state.current_market_data['atr_cache'] = {}
#             state.current_market_data['atr_cache'][timeframe] = rma
#             state.current_market_data['atr_last_update'] = datetime.now(pytz.UTC)
            
#             return rma
        
#         return state.current_market_data['atr_cache'][timeframe]

#     except Exception as e:
#         error_traceback = traceback.format_exc()
#         message(symbol, f"เกิดข้อผิดพลาดในการคำนวณ ATR: {str(e)}", "red")
#         message(symbol, f"Error: {error_traceback}", "red")
#         return None


# def calculate_rsi(close_prices, length):
#     """คำนวณ RSI โดยใช้ numpy (คงฟังก์ชันเดิมไว้เพราะทำงานได้ดีอยู่แล้ว)"""
#     if len(close_prices) < length + 1:
#         return np.zeros_like(close_prices)
        
#     deltas = np.diff(close_prices)
#     seed = deltas[:length+1]
#     up = seed[seed >= 0].sum()/length
#     down = -seed[seed < 0].sum()/length
    
#     if down == 0:
#         if up == 0:
#             rs = 1.0
#         else:
#             rs = float('inf')
#     else:
#         rs = up/down
        
#     rsi = np.zeros_like(close_prices)
#     rsi[:length] = 100. - 100./(1. + rs)

#     for i in range(length, len(close_prices)):
#         delta = deltas[i-1]
#         if delta > 0:
#             upval = delta
#             downval = 0.
#         else:
#             upval = 0.
#             downval = -delta

#         up = (up*(length-1) + upval)/length
#         down = (down*(length-1) + downval)/length
        
#         if down == 0:
#             if up == 0:
#                 rs = 1.0
#             else:
#                 rs = float('inf')
#         else:
#             rs = up/down
            
#         rsi[i] = 100. - 100./(1. + rs)

#     return np.clip(rsi, 0, 100)

# async def get_rsi_cross_last_candle(api_key, api_secret, symbol, timeframe, state, candle_index=0):
#     """คำนวณ RSI cross โดยใช้ค่า period แบบไดนามิกและเก็บค่า ATR"""
#     exchange = await create_future_exchange(api_key, api_secret)
    
#     try:
#         # คำนวณ period แบบไดนามิก
#         rsi_config = state.config.rsi_period
#         if not rsi_config.get('use_dynamic_period', True):
#             current_rsi_period = rsi_config['rsi_period_min']
#             state.current_atr_length_1 = None
#             state.current_atr_length_2 = None
#         else:
#             # คำนวณค่า ATR และเปรียบเทียบ
#             atr_short = await calculate_atr(
#                 api_key, api_secret, symbol, timeframe, state, 
#                 length=rsi_config['atr']['length1']
#             )
#             atr_long = await calculate_atr(
#                 api_key, api_secret, symbol, timeframe, state, 
#                 length=rsi_config['atr']['length2']
#             )
            
#             # เก็บค่า ATR ล่าสุด
#             state.current_atr_length_1 = atr_short
#             state.current_atr_length_2 = atr_long
            
#             if atr_short is None or atr_long is None:
#                 current_rsi_period = rsi_config['rsi_period_min']
#                 message(symbol, "ไม่สามารถคำนวณ ATR ได้ ใช้ค่า RSI period ต่ำสุด", "yellow")
#             else:
#                 atr_diff_percent = ((atr_short - atr_long) / atr_long) * 100
                
#                 """message(symbol, 
#                     f"ATR Diff: {atr_diff_percent:.2f}% " +
#                     f"(ATR{rsi_config['atr']['length1']}: {atr_short:.8f}, " +
#                     f"ATR{rsi_config['atr']['length2']}: {atr_long:.8f})", 
#                     "blue"
#                 )"""
                
#                 if atr_diff_percent >= rsi_config['atr']['max_percent']:
#                     current_rsi_period = rsi_config['rsi_period_max']
#                 elif atr_diff_percent <= rsi_config['atr']['min_percent']:
#                     current_rsi_period = rsi_config['rsi_period_min']
#                 else:
#                     period_range = rsi_config['rsi_period_max'] - rsi_config['rsi_period_min']
#                     volatility_range = rsi_config['atr']['max_percent'] - rsi_config['atr']['min_percent']
#                     period_step = (atr_diff_percent - rsi_config['atr']['min_percent']) / volatility_range
#                     current_rsi_period = int(round(rsi_config['rsi_period_min'] + (period_range * period_step)))

#         # เก็บค่า period ที่ใช้ล่าสุดใน state
#         state.current_rsi_period = current_rsi_period
        
#         # แสดงค่าทั้งหมดที่คำนวณได้
#         """message(symbol, f"ค่าที่ใช้:", "blue")
#         message(symbol, f"- RSI Period: {current_rsi_period}", "blue")
#         if state.current_atr_length_1 is not None:
#             message(symbol, f"- ATR{rsi_config['atr']['length1']}: {state.current_atr_length_1:.8f}", "blue")
#         if state.current_atr_length_2 is not None:
#             message(symbol, f"- ATR{rsi_config['atr']['length2']}: {state.current_atr_length_2:.8f}", "blue")"""

#         # ส่วนที่เหลือคงเดิม...
#         ohlcv = await fetch_ohlcv(symbol, timeframe, limit=100)
        
#         if not ohlcv or len(ohlcv) < current_rsi_period + 10:
#             return {
#                 'status': False,
#                 'type': None,
#                 'candle': None,
#                 'error': 'ข้อมูลไม่เพียงพอสำหรับการคำนวณ RSI'
#             }
            
#         await exchange.close()
        
#         closed_ohlcv = ohlcv[:-1]
#         df = pd.DataFrame(closed_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
#         local_tz = pytz.timezone('Asia/Bangkok')
#         df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms').dt.tz_localize(pytz.UTC).dt.tz_convert(local_tz)
        
#         with np.errstate(divide='ignore', invalid='ignore'):
#             df['rsi'] = calculate_rsi(df['close'].values, current_rsi_period)
        
#         if len(df) < 2 + candle_index:
#             return {
#                 'status': False,
#                 'type': None,
#                 'candle': None,
#                 'error': 'ข้อมูลไม่เพียงพอสำหรับการตรวจสอบ crossover'
#             }
            
#         last_closed_rsi = df['rsi'].iloc[-(1 + candle_index)]
#         prev_closed_rsi = df['rsi'].iloc[-(2 + candle_index)]
        
#         if np.isnan(last_closed_rsi) or np.isnan(prev_closed_rsi):
#             return {
#                 'status': False,
#                 'type': None,
#                 'candle': None,
#                 'error': 'ค่า RSI เป็น NaN'
#             }
        
#         result = {
#             'status': False,
#             'type': None,
#             'rsi_period_used': current_rsi_period,
#             'atr_values': {
#                 f'atr_{rsi_config["atr"]["length1"]}': state.current_atr_length_1,
#                 f'atr_{rsi_config["atr"]["length2"]}': state.current_atr_length_2
#             },
#             'candle': {
#                 'open': float(df['open'].iloc[-(1 + candle_index)]),
#                 'high': float(df['high'].iloc[-(1 + candle_index)]),
#                 'low': float(df['low'].iloc[-(1 + candle_index)]),
#                 'close': float(df['close'].iloc[-(1 + candle_index)]),
#                 'volume': float(df['volume'].iloc[-(1 + candle_index)]),
#                 'timestamp': int(df['timestamp'].iloc[-(1 + candle_index)].timestamp() * 1000),
#                 'time': df['timestamp'].iloc[-(1 + candle_index)].strftime('%d/%m/%Y %H:%M'),
#                 'rsi': round(float(last_closed_rsi), 2)
#             }
#         }
        
#         if prev_closed_rsi >= state.config.rsi_overbought and last_closed_rsi < state.config.rsi_overbought:
#             result['status'] = True
#             result['type'] = 'crossunder'
#         elif prev_closed_rsi <= state.config.rsi_oversold and last_closed_rsi > state.config.rsi_oversold:
#             result['status'] = True
#             result['type'] = 'crossover'
#         elif prev_closed_rsi < state.config.rsi_overbought and last_closed_rsi >= state.config.rsi_overbought:
#             result['status'] = True
#             result['type'] = 'crossover'
#         elif prev_closed_rsi > state.config.rsi_oversold and last_closed_rsi <= state.config.rsi_oversold:
#             result['status'] = True
#             result['type'] = 'crossunder'
        
#         return result

#     except Exception as e:
#         error_traceback = traceback.format_exc()
#         message(symbol, f"เกิดข้อผิดพลาดในการคำนวณ RSI: {str(e)}", "red")
#         message(symbol, f"Error: {error_traceback}", "red")
#         return None
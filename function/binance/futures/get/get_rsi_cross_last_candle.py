import ccxt.async_support as ccxt
import pandas as pd
import numpy as np
from datetime import datetime
import pytz

from function.binance.futures.system.create_future_exchange import create_future_exchange

def calculate_rsi(close_prices, length):
    deltas = np.diff(close_prices)
    seed = deltas[:length+1]
    up = seed[seed >= 0].sum()/length
    down = -seed[seed < 0].sum()/length
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
        rs = up/down
        rsi[i] = 100. - 100./(1. + rs)

    return rsi

async def get_rsi_cross_last_candle(api_key, api_secret, symbol, timeframe, rsi_length, oversold, overbought, candle_index=0):
    exchange = await create_future_exchange(api_key, api_secret)
    
    try:
        # Fetch 100 OHLCV data points
        ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, limit=100)
        await exchange.close()
        
        # Convert to DataFrame
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Convert UTC timestamp to local time
        local_tz = pytz.timezone('Asia/Bangkok')  # Adjust this to your local timezone
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms').dt.tz_localize(pytz.UTC).dt.tz_convert(local_tz)
        
        # Calculate RSI using only close prices
        df['rsi'] = calculate_rsi(df['close'].values, rsi_length)
        
        # Check for crossover/crossunder in the specified candles
        last_closed_rsi = df['rsi'].iloc[-(2 + candle_index)]
        prev_closed_rsi = df['rsi'].iloc[-(3 + candle_index)]
        
        result = {
            'status': False,
            'type': None,
            'candle': {
                'open': df['open'].iloc[-(2 + candle_index)],
                'high': df['high'].iloc[-(2 + candle_index)],
                'low': df['low'].iloc[-(2 + candle_index)],
                'close': df['close'].iloc[-(2 + candle_index)],
                'volume': df['volume'].iloc[-(2 + candle_index)],
                'time': df['timestamp'].iloc[-(2 + candle_index)].strftime('%d/%m/%Y %H:%M'),
                'rsi': round(last_closed_rsi, 2)
            }
        }
        
        # Check for crossUnderOverboughtReversal
        if prev_closed_rsi >= overbought and last_closed_rsi < overbought:
            result['status'] = True
            #result['type'] = 'crossUnderOverboughtReversal'
            result['type'] = 'crossunder'
        
        # Check for crossOverOversoldReversal
        elif prev_closed_rsi <= oversold and last_closed_rsi > oversold:
            result['status'] = True
            #result['type'] = 'crossOverOversoldReversal'
            result['type'] = 'crossover'
        
        # Check for crossOverOverbought
        elif prev_closed_rsi < overbought and last_closed_rsi >= overbought:
            result['status'] = True
            #result['type'] = 'crossOverOverbought'
            result['type'] = 'crossover'
        
        # Check for crossUnderOversold
        elif prev_closed_rsi > oversold and last_closed_rsi <= oversold:
            result['status'] = True
            #result['type'] = 'crossUnderOversold'
            result['type'] = 'crossunder'
        
        return result

    except ccxt.BaseError as e:
        print(f"An error occurred: {str(e)}")
        return None
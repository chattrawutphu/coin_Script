import ccxt.async_support as ccxt
from datetime import datetime, timedelta
import pytz

from function.binance.futures.order.other.get_kline_data import fetch_ohlcv
from function.binance.futures.system.create_future_exchange import create_future_exchange

async def get_wait_candle_end(api_key, api_secret, symbol, timeframe, num_candles=1):
    exchange = await create_future_exchange(api_key, api_secret)
    
    try:
        # Fetch the latest candle
        ohlcv = await fetch_ohlcv(symbol, timeframe, limit=1)
        await exchange.close()
        
        if not ohlcv:
            return {'status': False, 'message': 'Failed to fetch candle data'}
        
        # Get the timestamp of the latest candle
        latest_candle_time = datetime.fromtimestamp(ohlcv[0][0] / 1000, tz=pytz.UTC)
        
        # Calculate the end time of the next candle
        if timeframe.endswith('h'):
            hours = int(timeframe[:-1])
            next_candle_end = latest_candle_time + timedelta(hours=hours * (num_candles + 1))
        elif timeframe.endswith('m'):
            minutes = int(timeframe[:-1])
            next_candle_end = latest_candle_time + timedelta(minutes=minutes * (num_candles + 1))
        else:
            return {'status': False, 'message': 'Unsupported timeframe'}
        
        # Check if the next candle has ended
        current_time = datetime.now(pytz.UTC)
        if current_time >= next_candle_end:
            # Fetch the data of the newly closed candle
            ohlcv = await fetch_ohlcv(symbol, timeframe, limit=1)
            await exchange.close()
            
            if not ohlcv:
                return {'status': False, 'message': 'Failed to fetch new candle data'}
            
            # Convert the candle data to a dictionary
            candle_data = {
                'timestamp': datetime.fromtimestamp(ohlcv[0][0] / 1000, tz=pytz.UTC),
                'open': ohlcv[0][1],
                'high': ohlcv[0][2],
                'low': ohlcv[0][3],
                'close': ohlcv[0][4],
                'volume': ohlcv[0][5]
            }
            
            return {
                'status': True,
                'candle': candle_data
            }
        else:
            # Calculate time remaining until next candle ends
            time_remaining = next_candle_end - current_time
            
            return {
                'status': False,
                'message': 'Next candle has not ended yet',
                'time_remaining': str(time_remaining),
                'next_candle_end': next_candle_end.strftime('%Y-%m-%d %H:%M:%S %Z')
            }

    except ccxt.BaseError as e:
        print(f"An error occurred: {str(e)}")
        return {'status': False, 'message': str(e)}
import asyncio
from datetime import datetime
import json
import time
import traceback

import pytz

from function.binance.futures.check.check_future_available_balance import check_future_available_balance
from function.binance.futures.check.check_position import check_position
from function.binance.futures.check.check_price import check_price
from function.binance.futures.check.check_server_status import check_server_status
from function.binance.futures.check.check_user_api_status import check_user_api_status
from function.binance.futures.get.get_rsi_cross_last_candle import get_rsi_cross_last_candle
from function.binance.futures.get.get_wait_candle_end import get_wait_candle_end
from function.binance.futures.order.change_stoploss_to_price import change_stoploss_to_price
from function.binance.futures.order.create_order import create_order
from function.binance.futures.order.get_all_order import clear_all_orders, get_all_order
from function.binance.futures.order.other.get_closed_position import get_amount_of_closed_position, get_closed_position_side
from function.binance.futures.order.other.get_future_market_price import get_future_market_price
from function.binance.futures.order.other.get_position_side import get_position_side
from function.binance.futures.order.swap_position_side import swap_position_side
from function.binance.futures.system.create_future_exchange import create_future_exchange
from function.codelog import codelog
from function.message import message

# api_key = '6041331240427dbbf26bd671beee93f6686b57dde4bde5108672963fad02bf2e'
# api_secret = '560764a399e23e9bc5e24d041bd3b085ee710bf08755d26ff4822bfd9393b11e'

#api_key = 'eQ7bhgkqMUJwAfGhGVwreXU63ixTV0fZEbytCUy9OXcV0sWwK2tvUPeGC4QQUIT4'
#api_secret = 'MyLeaA9wta1Cr5vXEduYUkvOTU1Ws3MutdfLIDxa9FO5mUUPcbs6tAL6v3XY5j1o'

api_key = 'cos73h05s3oxvSK2u7YG2k0mIiu5npSVIXTdyIXXUVNJQOKbRybPNlGOeZNvunVG'
api_secret = 'Zim1iiECBaYdtx3rVlN5mpQ05iQWRXDXU0EBW8LmQW8Ns2X07HhKfIs4Kj3PLzgO'

# Constants for price changes
PRICE_CHANGE_THRESHOLD = 0.0001  # 0.1%
PRICE_INCREASE = 1 + PRICE_CHANGE_THRESHOLD  # 1.001
PRICE_DECREASE = 1 - PRICE_CHANGE_THRESHOLD  # 0.999
PRICE_CHANGE_MAXPERCENT = 5

async def check_new_candle_and_rsi(api_key, api_secret, symbol, timeframe):
    last_candle_time = None
    last_candle_cross = None
    last_focus_price = None
    last_focus_stopprice = None
    is_wait_candle = False
    is_in_position = False
    is_swapping = False
    isTry_last_entry = False
    entry_candle = None
    entry_price = None
    entry_side = None
    entry_stoploss_price = None
    
    exchange = await create_future_exchange(api_key, api_secret)

    is_in_position = await check_position(api_key, api_secret, symbol)
    print(f"is_in_position = {is_in_position}")

    while True:
        try:
            price = await get_future_market_price(api_key, api_secret, symbol)
            if price is None:
                print("Unable to fetch market price. Skipping this iteration.")
                await asyncio.sleep(1)
                continue

            if is_wait_candle == True:
                side = await get_position_side(api_key, api_secret, symbol)
                if side == 'buy':
                    if price > last_candle_cross['candle']['high'] * PRICE_INCREASE:
                        await change_stoploss_to_price(api_key, api_secret, symbol, last_candle_cross['candle']['low'] * PRICE_DECREASE)
                        print(f"change stop loss to {last_candle_cross['candle']['low'] * PRICE_DECREASE}")
                        is_wait_candle = False
                elif side == 'sell':
                    if price < last_candle_cross['candle']['low'] * PRICE_DECREASE:
                        await change_stoploss_to_price(api_key, api_secret, symbol, last_candle_cross['candle']['high'] * PRICE_INCREASE)
                        print(f"change stop loss to {last_candle_cross['candle']['high'] * PRICE_INCREASE}")
                        is_wait_candle = False

            if isTry_last_entry == True:
                current_time = datetime.now(pytz.UTC)
                if last_candle_cross and 'candle' in last_candle_cross and 'time' in last_candle_cross['candle']:
                    last_cross_time = datetime.strptime(last_candle_cross['candle']['time'], '%d/%m/%Y %H:%M').replace(tzinfo=pytz.UTC)
                    time_difference = current_time - last_cross_time
                    candles_passed = time_difference.total_seconds() / (timeframe_to_seconds(timeframe))

                    ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, since=int(last_cross_time.timestamp() * 1000))
                    
                    if ohlcv:
                        if last_candle_cross['type'] == 'crossunder':
                            lowest_price = min([candle[3] for candle in ohlcv])  # Find lowest low
                            reference_price = last_candle_cross['candle'].get('low')
                            if reference_price is not None:
                                price_change_percent = (lowest_price - reference_price) / reference_price * 100
                            else:
                                print("Reference price (low) is None. Skipping price change calculation.")
                                continue
                        else:  # crossover
                            highest_price = max([candle[2] for candle in ohlcv])  # Find highest high
                            reference_price = last_candle_cross['candle'].get('high')
                            if reference_price is not None:
                                price_change_percent = (highest_price - reference_price) / reference_price * 100
                            else:
                                print("Reference price (high) is None. Skipping price change calculation.")
                                continue

                        if candles_passed <= 5 and abs(price_change_percent) < PRICE_CHANGE_MAXPERCENT:
                            closed_position_amount = await get_amount_of_closed_position(api_key, api_secret, symbol)
                            if closed_position_amount is not None:
                                if last_candle_cross['type'] == 'crossover':
                                    if price > last_candle_cross['candle'].get('low', 0) * PRICE_DECREASE and price < (last_candle_cross['candle'].get('high', 0) * PRICE_INCREASE) * 1.02:
                                        await create_order(api_key, api_secret, symbol=symbol, side='buy', price='now', quantity=abs(closed_position_amount), order_type='market')
                                        await create_order(api_key, api_secret, symbol=symbol, side='sell', price=str(last_candle_cross['candle'].get('low', 0) * PRICE_DECREASE), quantity='MAX', order_type='STOPLOSS_MARKET')
                                        isTry_last_entry = False
                                else:
                                    if price < last_candle_cross['candle'].get('high', 0) * PRICE_INCREASE and price > (last_candle_cross['candle'].get('low', 0) * PRICE_DECREASE) * 1.02:
                                        await create_order(api_key, api_secret, symbol=symbol, side='sell', price='now', quantity=abs(closed_position_amount), order_type='market')
                                        await create_order(api_key, api_secret, symbol=symbol, side='buy', price=str(last_candle_cross['candle'].get('high', 0) * PRICE_INCREASE), quantity='MAX', order_type='STOPLOSS_MARKET')
                                        isTry_last_entry = False
                            else:
                                print("Unable to get closed position amount. Skipping order creation.")
                    else:
                        print("No OHLCV data available. Skipping this iteration.")
                else:
                    print("Invalid last_candle_cross data. Skipping this iteration.")
                    isTry_last_entry = False

            if is_in_position and entry_candle:
                current_candle = await get_current_candle(api_key, api_secret, symbol, timeframe)
                if current_candle:
                    time_since_entry = current_candle['timestamp'] - entry_candle['timestamp']
                    candles_since_entry = (time_since_entry // get_timeframe_milliseconds(timeframe)) - 1
                    
                    if candles_since_entry >= 3:
                        position_side = await get_position_side(api_key, api_secret, symbol)
                        if position_side:
                            new_stoploss = await adjust_stoploss(api_key, api_secret, symbol, timeframe, position_side, entry_candle['timestamp'])
                            if new_stoploss:
                                print(f"ปรับ Stoploss เป็น {new_stoploss} (tree tricker)")
                        else:
                            print("Unable to get position side. Skipping stoploss adjustment.")
                    else:
                        print(f"รอปรับ Stoploss ในอีก {3 - candles_since_entry} แท่ง")
                else:
                    print("Unable to get current candle. Skipping stoploss adjustment.")

            if is_in_position == True and is_swapping == False and await check_position(api_key, api_secret, symbol) == False:
                await clear_all_orders(api_key, api_secret, symbol)
                print('position ถูก close แล้ว!')
                is_in_position = False
                if is_wait_candle == True:
                    closed_position_amount = await get_amount_of_closed_position(api_key, api_secret, symbol)
                    closed_position_side = await get_closed_position_side(api_key, api_secret, symbol)
                    
                    if closed_position_side == 'buy':
                        new_entry_side = 'sell'
                        new_entry_price = price
                        new_stoploss_price = last_candle_cross['candle']['high'] * PRICE_INCREASE
                    else:
                        new_entry_side = 'buy'
                        new_entry_price = price
                        new_stoploss_price = last_candle_cross['candle']['low'] * PRICE_DECREASE
                    
                    await create_order(api_key, api_secret, symbol=symbol, side=new_entry_side, price='now', quantity=abs(closed_position_amount), order_type='market')
                    await create_order(api_key, api_secret, symbol=symbol, side=('sell' if new_entry_side=='buy' else 'buy'), price=str(new_stoploss_price), quantity='MAX', order_type='STOPLOSS_MARKET')
                    
                    print(f'เข้า {new_entry_side} position ตรงข้ามสำเร็จ ขนาด: {abs(closed_position_amount)}, Stoploss: {new_stoploss_price}')
                    is_in_position = True
                    is_wait_candle = False
                else:
                    isTry_last_entry = True
            
            if last_focus_price is not None:
                side = await get_position_side(api_key, api_secret, symbol)
                if side == 'buy':
                    if price < last_focus_price * PRICE_DECREASE:
                        is_swapping = True
                        await swap_position_side(api_key, api_secret, symbol)
                        await clear_all_orders(api_key, api_secret, symbol)
                        await create_order(api_key, api_secret, symbol=symbol, side='buy', price=str(last_candle_cross['candle']['high'] * PRICE_INCREASE), quantity='MAX', order_type='STOPLOSS_MARKET')
                        print(f"Swap position form {side}")
                        is_swapping = False
                        last_focus_price = None
                        entry_stoploss_price = None
                    elif price > last_focus_stopprice * PRICE_INCREASE:
                        await change_stoploss_to_price(api_key, api_secret, symbol, last_focus_price)
                        print(f"change stop loss to {last_focus_price}")
                        last_focus_price = None
                        entry_stoploss_price = None
                elif side == 'sell':
                    if price > last_focus_price * PRICE_INCREASE:
                        is_swapping = True
                        await swap_position_side(api_key, api_secret, symbol)
                        await clear_all_orders(api_key, api_secret, symbol)
                        await create_order(api_key, api_secret, symbol=symbol, side='sell', price=str(last_candle_cross['candle']['low'] * PRICE_DECREASE), quantity='MAX', order_type='STOPLOSS_MARKET')
                        print(f"Swap position form {side}")
                        is_swapping = False
                        last_focus_price = None
                        entry_stoploss_price = None
                    elif price < last_focus_stopprice * PRICE_DECREASE:
                        await change_stoploss_to_price(api_key, api_secret, symbol, last_focus_price)
                        print(f"change stop loss to {last_focus_price}")
                        last_focus_price = None
                        entry_stoploss_price = None
            
            if entry_price is not None:
                if entry_side == 'buy':
                    if price > entry_price * PRICE_INCREASE:
                        await create_order(api_key, api_secret, symbol=symbol, side=entry_side, price='now', quantity='25$', order_type='market')
                        await create_order(api_key, api_secret, symbol=symbol, side='sell', price=str(entry_stoploss_price * PRICE_DECREASE), quantity='MAX', order_type='STOPLOSS_MARKET')
                        print('เข้า long position สำเร็จ')
                        is_in_position = True
                        entry_candle = await get_current_candle(api_key, api_secret, symbol, timeframe)
                        entry_price = None
                        entry_stoploss_price = None
                        entry_side = None
                    elif price < entry_stoploss_price * PRICE_DECREASE:
                        print('ยกเลิก long entry')
                        entry_price = None
                        entry_stoploss_price = None
                        entry_side = None
                    else:
                        print(f'รอราคาทะลุ {entry_price} เพื่อ long')
                elif entry_side == 'sell':
                    if price < entry_price * PRICE_DECREASE:
                        await create_order(api_key, api_secret, symbol=symbol, side=entry_side, price='now', quantity='25$', order_type='market')
                        await create_order(api_key, api_secret, symbol=symbol, side='buy', price=str(entry_stoploss_price * PRICE_INCREASE), quantity='MAX', order_type='STOPLOSS_MARKET')
                        print('เข้า short position สำเร็จ')
                        is_in_position = True
                        entry_candle = await get_current_candle(api_key, api_secret, symbol, timeframe)
                        entry_price = None
                        entry_stoploss_price = None
                        entry_side = None
                    elif price > entry_stoploss_price * PRICE_INCREASE:
                        print('ยกเลิก short entry')
                        entry_price = None
                        entry_stoploss_price = None
                        entry_side = None
                    else:
                        print(f'รอราคาทะลุ {entry_price} เพื่อ short')

            ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, limit=1)
            
            if ohlcv and len(ohlcv) > 0:
                current_candle_time = datetime.fromtimestamp(ohlcv[0][0] / 1000, tz=pytz.UTC)
                
                # Check for new candle
                if last_candle_time is None or current_candle_time > last_candle_time:
                    last_candle_time = current_candle_time
                    side = await get_position_side(api_key, api_secret, symbol)
                    
                    if is_wait_candle and side is not None:
                        is_wait_candle = False
                        if last_candle_cross and 'candle' in last_candle_cross:
                            last_focus_price = min(last_candle_cross['candle'].get('low', 0), ohlcv[0][3]) if side == 'buy' else max(last_candle_cross['candle'].get('high', 0), ohlcv[0][2])
                            last_focus_stopprice = max(last_candle_cross['candle'].get('high', 0), ohlcv[0][2]) if side == 'buy' else min(last_candle_cross['candle'].get('low', 0), ohlcv[0][3])
                            print('ปิดแท่งเทียงหลังเจอสัญตรงกันข้าม! มาลุ้นกันว่าจะ swap position หรือขยับ stoploss')

                    # Check for RSI cross
                    isRsiCross = await get_rsi_cross_last_candle(api_key, api_secret, symbol, timeframe, 7, 32, 68)
                    if isRsiCross and 'status' in isRsiCross:
                        print(f"RSI Cross result: {isRsiCross}")
                        
                        if isRsiCross['status']:
                            if is_in_position == True and side is not None:
                                print(f"side = {side} // isRsiCross['type'] = {isRsiCross['type']}")
                                if (side == 'buy' and isRsiCross['type'] == 'crossunder') or (side == 'sell' and isRsiCross['type'] == 'crossover'):
                                    last_candle_cross = isRsiCross
                                    last_focus_price = None
                                    last_focus_stopprice = None
                                    is_wait_candle = True
                                    print('พบสัญญาณตรงกันข้าม! รอปิดแท่งเทียน!')
                                else:
                                    last_focus_price = None
                            elif not is_in_position:
                                await clear_all_orders(api_key, api_secret, symbol)
                                if 'candle' in isRsiCross:
                                    entry_price = isRsiCross['candle'].get('high') if isRsiCross['type'] == 'crossover' else isRsiCross['candle'].get('low')
                                    entry_stoploss_price = isRsiCross['candle'].get('low') if isRsiCross['type'] == 'crossover' else isRsiCross['candle'].get('high')
                                    entry_side = 'buy' if isRsiCross['type'] == 'crossover' else 'sell'
                    else:
                        print("Invalid RSI cross data. Skipping this iteration.")

            await asyncio.sleep(1)  # Adjust as needed

        except Exception as e:
            print(f"An error occurred: {str(e)}")
            await asyncio.sleep(1)  # Wait before retrying

async def adjust_stoploss(api_key, api_secret, symbol, timeframe, position_side, entry_time):
    exchange = await create_future_exchange(api_key, api_secret)
    
    try:
        current_time = int(time.time() * 1000)
        
        # Convert entry_time to milliseconds timestamp if it's not already
        if isinstance(entry_time, datetime):
            entry_timestamp = int(entry_time.timestamp() * 1000)
        else:
            entry_timestamp = entry_time
        
        # Calculate the number of candles passed since entry
        candles_since_entry = (current_time - entry_timestamp) // get_timeframe_milliseconds(timeframe)
        
        # Limit the number of candles to fetch (minimum 3, maximum 5)
        candles_to_fetch = min(max(candles_since_entry, 3), 5)
        
        # Fetch the required number of candles
        ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, limit=candles_to_fetch)
        await exchange.close()
        
        if not ohlcv:
            print("No OHLCV data available. Skipping stoploss adjustment.")
            return None
        
        # Extract low and high prices
        lows = [candle[3] for candle in ohlcv]  # Low prices
        highs = [candle[2] for candle in ohlcv]  # High prices
        
        new_stoploss = None
        
        if position_side == 'buy':
            # Check for at least 3 consecutively higher lows
            for i in range(len(lows) - 2):
                if lows[i] < lows[i+1] < lows[i+2]:
                    new_stoploss = lows[i+1]
                    break
            
            if new_stoploss is None:
                # If no 3 consecutive higher lows, find the lowest of the last 3 lows
                new_stoploss = min(lows[-3:])
        
        elif position_side == 'sell':
            # Check for at least 3 consecutively lower highs
            for i in range(len(highs) - 2):
                if highs[i] > highs[i+1] > highs[i+2]:
                    new_stoploss = highs[i+1]
                    break
            
            if new_stoploss is None:
                # If no 3 consecutive lower highs, find the highest of the last 3 highs
                new_stoploss = max(highs[-3:])
        
        else:
            raise ValueError("Invalid position side. Must be 'buy' or 'sell'.")
        
        # Adjust the stoploss
        if new_stoploss is not None:
            await change_stoploss_to_price(api_key, api_secret, symbol, new_stoploss)
            print(f"Adjusted stoploss to {new_stoploss}")
        else:
            print("No adjustment to stoploss needed")
        
        return new_stoploss
    
    except Exception as e:
        print(f"An error occurred while adjusting stoploss: {str(e)}")
        return None

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
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    
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
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    
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
        print(f"Error fetching current candle: {str(e)}")
    return None

async def main():
    try:
        symbol = 'ETHUSDT'
        timeframe = '3m'
        await check_new_candle_and_rsi(api_key, api_secret, symbol, timeframe)
        #await swap_position_side(api_key, api_secret, symbol)
        """

        if isRsiCross:
            print("RSI Cross detected:")
            print(f"Status: {isRsiCross['status']}")
            print(f"Type: {isRsiCross['type']}")
            print("Candle information:")
            for key, value in isRsiCross['candle'].items():
                print(f"  {key}: {value}")
        else:
            print("Failed to get RSI cross information or no cross detected.")
        
        if await check_server_status(api_key, api_secret):
             await codelog(api_key, api_secret, "s1001t")
             if await check_user_api_status(api_key, api_secret):
                 await codelog(api_key, api_secret, "s1002t")
                 if await check_price(api_key, api_secret, 'BTCUSDT', '80000', '<=', condition_price="add/10_lastint/1h"):
                     await codelog(api_key, api_secret, "c1001t", *['BTCUSDT', '80000', '<='])
                     if await check_future_available_balance(api_key, api_secret, '500', '>='):
                         await codelog(api_key, api_secret, "c1002t", *['500', '>='])
                         if await check_position(api_key, api_secret, 'BTCUSDT') == False:
                             await codelog(api_key, api_secret, "c1003t", *['BTCUSDT'])
                           
                            #  order = await create_order(api_key, api_secret, symbol='BTCUSDT', side='buy', price='40000', quantity='500$', order_type='limit')
                            #  if order != None:
                            #      await codelog(api_key, api_secret, "a1001t", *['BTCUSDT', 'buy', '40000', '500$', 'llimit'])

                         else:
                             await codelog(api_key, api_secret, "c1003f", *['BTCUSDT'])
                     else:
                         await codelog(api_key, api_secret, "c1002f", *['500', '>='])
                 else:
                     await codelog(api_key, api_secret, "c1001f", *['BTCUSDT', '80000', '<='])
             else:
                 await codelog(api_key, api_secret, "s1002f")
         else:
             await codelog(api_key, api_secret, "s1001f")
        # while True:
        #     price = await get_future_market_price(api_key, api_secret, "DOGEUSDT")
        #     print(price)
        #     time.sleep(1) """
    except Exception as e:
        error_traceback = traceback.format_exc()
        message(f"พบข้อผิดพลาด", "yellow")
        print(f"Error: {error_traceback}")


if __name__ == "__main__":
    asyncio.run(main())
    #asyncio.run(main_trading_loop(api_key, api_secret))
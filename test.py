"""
    wait_position = False

    fun check_swap_point(api_key, api_secret,'BTCUSDT', side):
        if side == "buy":
            if price < swap_point:
                swap_position()
            if price > swap_point_stoploss:
                change_stoploss_price()
        else:
            if price > swap_point:
                swap_position()
            if price < swap_point_stoploss:
                change_stoploss_price()
        clear_swap_point()
    
    fun check_wait_position():
        if wait_position == True:
            if await check_position(api_key, api_secret, 'BTCUSDT') == True:
                alert
                wait_position = False
    

    while True:
        check_wait_position()
        check_swap_point()
        isRsiCross = check_rsi_cross_last_candle(api_key, api_secret,'BTCUSDT','4h',7,32,68);
        if isRsiCross['status'] != False:
            if await check_position(api_key, api_secret, 'BTCUSDT') == True:
                candleEnd = wait_candle_end(api_key, api_secret, 'BTCUSDT', 1, isRsiCross['candle']['time'])
                if candleEnd['status'] == True:
                    swap_point_price_1 = isRsiCross['candle']['low'] if side == "buy"  else isRsiCross['candle']['high'] 
                    swap_point_price_2 = candleEnd['candle']['low'] if side == "buy"  else candleEnd['candle']['high'] 
                    if side == "buy":
                        swap_point_price = min(swap_point_price_1, swap_point_price_2)  # เลือก low ต่ำสุด
                    else:
                        swap_point_price = max(swap_point_price_1, swap_point_price_2)  # เลือก high สูงสุด
                    await create_swap_point(api_key, api_secret, symbol='BTCUSDT', side=side, swap_point_price, swap_point_stoploss_price)
            else:
                side = 'buy' if isRsiCross['side'] == "crossover" else 'sell'
                price = 'low' if side == 'buy' else 'high'
                clear_all_order(api_key, api_secret, symbol='BTCUSDT')
                await create_order(api_key, api_secret, symbol='BTCUSDT', side=side,price=price quantity='100%', order_type='stopmarket')
                await create_Stoploss()
                wait_position = True
"""
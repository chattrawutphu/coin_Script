from function.binance.futures.system.create_future_exchange import create_future_exchange

async def get_closed_position_side(api_key, api_secret, symbol):
    exchange = await create_future_exchange(api_key, api_secret)
    try:
        # Fetch recent trades
        trades = await exchange.fetch_my_trades(symbol, limit=1)
        
        if trades:
            last_trade = trades[-1]
            # The 'side' in the last trade will be the opposite of the closed position
            return 'sell' if last_trade['side'] == 'buy' else 'buy'
        else:
            print("No recent trades found")
            return None
    
    except Exception as e:
        print(f"An error occurred while getting closed position side: {str(e)}")
        return None
    
    finally:
        await exchange.close()

async def get_amount_of_closed_position(api_key, api_secret, symbol):
    exchange = await create_future_exchange(api_key, api_secret)
    try:
        # Fetch recent trades
        trades = await exchange.fetch_my_trades(symbol, limit=1)
        
        if trades:
            last_trade = trades[-1]
            # The 'amount' in the last trade will be the amount of the closed position
            return last_trade['amount']
        else:
            print("No recent trades found")
            return 0
    
    except Exception as e:
        print(f"An error occurred while getting closed position amount: {str(e)}")
        return 0
    
    finally:
        await exchange.close()
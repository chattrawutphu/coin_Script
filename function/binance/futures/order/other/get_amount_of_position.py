import traceback
import ccxt.async_support as ccxt
from config import default_testnet as testnet
from function.binance.futures.order.other.get_adjust_precision_quantity import get_adjust_precision_quantity
from function.binance.futures.system.create_future_exchange import create_future_exchange

async def get_amount_of_position(api_key, api_secret, symbol):
    exchange = await create_future_exchange(api_key, api_secret)

    try:
        positions = await exchange.fetch_positions()
        
        # Convert input symbol to the format used by the exchange
        exchange_symbol = symbol.replace("USDT", "/USDT:USDT")
        
        for position in positions:
            if position['symbol'] == exchange_symbol:
                #print(position)  # For debugging
                # Use 'contracts' instead of 'amount'
                contracts = float(position.get('contracts', 0))
                if contracts != 0:
                    side = 1 if position.get('side', '').lower() == 'long' else -1
                    amount = contracts * side
                    return await get_adjust_precision_quantity(symbol, amount)

        return 0

    except Exception as e:
        print(f"Error in get_amount_of_position: {e}")
        print(traceback.format_exc())
        return 0

    finally:
        await exchange.close()
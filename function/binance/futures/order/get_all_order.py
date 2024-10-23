import traceback
import ccxt.async_support as ccxt
from config import default_testnet as testnet
from function.binance.futures.system.create_future_exchange import create_future_exchange
from function.message import message

async def get_all_order(api_key, api_secret, symbol=None):
    exchange = await create_future_exchange(api_key, api_secret, warnOnFetchOpenOrdersWithoutSymbol=False)

    orders = await exchange.fetch_open_orders(symbol)
    await exchange.close()
    return orders

async def clear_all_orders(api_key, api_secret, symbol):
    exchange = await create_future_exchange(api_key, api_secret)
    try:
        # Fetch all open orders for the specified symbol
        open_orders = await get_all_order(api_key, api_secret, symbol)
        
        cancelled_orders = []
        for order in open_orders:
            try:
                # Cancel the order
                await exchange.cancel_order(order['id'], symbol)
                cancelled_orders.append(order['id'])
                #print(f"Cancelled order: {order['id']}")
            except Exception as e:
                error_traceback = traceback.format_exc()
                message(symbol,f"Error cancelling order {order['id']}: {str(e)}", "yellow")
                message(symbol, "________________________________", "red")
                print(f"Error: {error_traceback}")
                message(symbol, "________________________________", "red")
        
        #print(f"Cancelled {len(cancelled_orders)} orders for {symbol}")
        return cancelled_orders
    except Exception as e:
        print(f"An error occurred while clearing orders: {str(e)}")
        return []
    finally:
        await exchange.close()
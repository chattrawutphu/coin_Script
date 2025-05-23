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
       
       if not open_orders:
           #message(symbol, "ไม่พบ orders ที่เปิดอยู่", "blue") 
           return []
           
       cancelled_orders = []
       for order in open_orders:
           try:
               # ตรวจสอบว่า order ยังมีอยู่จริงก่อนยกเลิก
               order_detail = None
               try:
                   order_detail = await exchange.fetch_order(order['id'], symbol)
               except Exception as e:
                   if 'Unknown order sent' in str(e):
                       # ข้าม order ที่ไม่มีอยู่แล้ว
                       continue
                   raise e

               if order_detail and order_detail['status'] not in ['closed', 'canceled']:
                   # Cancel the order
                   await exchange.cancel_order(order['id'], symbol)
                   cancelled_orders.append(order['id'])
                   #message(symbol, f"Cancelled order: {order['id']}", "blue")

           except Exception as e:
               if 'Unknown order sent' in str(e):
                   # ข้าม error นี้
                   continue
               else:
                   error_traceback = traceback.format_exc()
                   message(symbol,f"Error cancelling order {order['id']}: {str(e)}", "yellow")
                   message(symbol, "________________________________", "red")
                   message(symbol, f"Error: {error_traceback}", "red")
                   message(symbol, "________________________________", "red")
       
       return cancelled_orders

   except Exception as e:
       error_traceback = traceback.format_exc()
       message(symbol, f"เกิดข้อผิดพลาดในการยกเลิก Orders: {str(e)}", "red") 
       message(symbol, f"Error: {error_traceback}", "red")
       return []
       
   finally:
       await exchange.close()

async def clear_stoploss(api_key, api_secret, symbol):
    """ลบเฉพาะ stoploss orders ที่มีอยู่"""
    exchange = await create_future_exchange(api_key, api_secret)
    try:
        # ดึง orders ที่เปิดอยู่ทั้งหมด
        open_orders = await get_all_order(api_key, api_secret, symbol)
        
        if not open_orders:
            return []
            
        cancelled_orders = []
        for order in open_orders:
            try:
                # ตรวจสอบว่าเป็น stop_market order หรือไม่
                if order['type'] in ['stop_market', 'stop']:
                    # ตรวจสอบว่า order ยังมีอยู่จริง
                    order_detail = None
                    try:
                        order_detail = await exchange.fetch_order(order['id'], symbol)
                    except Exception as e:
                        if 'Unknown order sent' in str(e):
                            continue
                        raise e

                    if order_detail and order_detail['status'] not in ['closed', 'canceled']:
                        # ยกเลิก stoploss order
                        await exchange.cancel_order(order['id'], symbol)
                        cancelled_orders.append(order['id'])

            except Exception as e:
                if 'Unknown order sent' in str(e):
                    continue
                else:
                    error_traceback = traceback.format_exc()
                    message(symbol, f"Error cancelling stoploss order {order['id']}: {str(e)}", "yellow")
                    message(symbol, f"Error: {error_traceback}", "red")
        
        return cancelled_orders

    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"เกิดข้อผิดพลาดในการยกเลิก Stoploss Orders: {str(e)}", "red")
        message(symbol, f"Error: {error_traceback}", "red")
        return []
    finally:
        await exchange.close()

async def clear_tp_orders(api_key: str, api_secret: str, symbol: str):
    """ลบ take profit orders ที่มีอยู่"""
    exchange = await create_future_exchange(api_key, api_secret)
    try:
        # ดึง orders ที่เปิดอยู่ทั้งหมด
        open_orders = await get_all_order(api_key, api_secret, symbol)
        
        if not open_orders:
            return []
            
        cancelled_orders = []
        for order in open_orders:
            try:
                # ตรวจสอบว่าเป็น take_profit_market order หรือไม่
                if order['type'].lower() in ['take_profit_market', 'take_profit']:
                    # ตรวจสอบว่า order ยังมีอยู่จริง
                    order_detail = None
                    try:
                        order_detail = await exchange.fetch_order(order['id'], symbol)
                    except Exception as e:
                        if 'Unknown order sent' in str(e):
                            continue
                        raise e

                    if order_detail and order_detail['status'] not in ['closed', 'canceled']:
                        # ยกเลิก take profit order
                        await exchange.cancel_order(order['id'], symbol)
                        cancelled_orders.append(order['id'])
                        message(symbol, f"ยกเลิก TP Order {order['id']}", "cyan")

            except Exception as e:
                if 'Unknown order sent' in str(e):
                    continue
                else:
                    error_traceback = traceback.format_exc()
                    message(symbol, f"Error cancelling TP order {order['id']}: {str(e)}", "yellow")
                    message(symbol, f"Error: {error_traceback}", "red")
        
        return cancelled_orders

    except Exception as e:
        error_traceback = traceback.format_exc()
        message(symbol, f"เกิดข้อผิดพลาดในการยกเลิก Take Profit Orders: {str(e)}", "red")
        message(symbol, f"Error: {error_traceback}", "red")
        return []
    finally:
        await exchange.close()
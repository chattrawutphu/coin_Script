from binance.client import Client
from config import api_key, api_secret
from datetime import datetime

client = Client(api_key, api_secret)

def get_last_position_history(symbol):
    position_history = client.futures_account_trades(symbol=symbol)
    last_position = position_history[-1]

    # แปลง timestamp ให้เป็นรูปแบบวันที่ 'DD-MM-YYYY'
    timestamp = int(last_position['time'])
    time_obj = datetime.fromtimestamp(timestamp / 1000)
    formatted_time = time_obj.strftime('%d-%m-%Y')

    # สร้าง dictionary เพื่อเก็บข้อมูลที่ต้องการ
    result = {
        'symbol': last_position['symbol'],
        'side': last_position['side'],
        'price': float(last_position['price']),
        'qty': float(last_position['qty']),
        'realizedPnl': float(last_position['realizedPnl']),
        'commission': float(last_position['commission']),
        'quoteQty': float(last_position['quoteQty']),
        'time': formatted_time  # ใช้เวลาที่แปลงแล้ว
    }

    return result
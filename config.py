api_key = 'cos73h05s3oxvSK2u7YG2k0mIiu5npSVIXTdyIXXUVNJQOKbRybPNlGOeZNvunVG'
api_secret = 'Zim1iiECBaYdtx3rVlN5mpQ05iQWRXDXU0EBW8LmQW8Ns2X07HhKfIs4Kj3PLzgO'

"""api_key = '6041331240427dbbf26bd671beee93f6686b57dde4bde5108672963fad02bf2e'
api_secret = '560764a399e23e9bc5e24d041bd3b085ee710bf08755d26ff4822bfd9393b11e'"""

TRADING_CONFIG = {
    'ETHUSDT': {
        'timeframe': '3m',
        'entry_amount': '25$',
        'rsi_period': 7,
        'rsi_overbought': 68,
        'rsi_oversold': 32
    }
}

PRICE_CHANGE_THRESHOLD = 0.0001  # 0.1%
PRICE_INCREASE = 1 + PRICE_CHANGE_THRESHOLD  # 1.001
PRICE_DECREASE = 1 - PRICE_CHANGE_THRESHOLD  # 0.999
PRICE_CHANGE_MAXPERCENT = 0.5
MAX_CANDLES_TO_FETCH = 5
MIN_CANDLES_TO_FETCH = 3

default_testnet = False
default_show_message = [
    True,
    True,
    True,
    True,
    True
]
default_log_secondary_language = False #server log เป็นภาษาไทย
default_log_database = False #ยอมรับให้เก็บข้อมูลลง database

symbols_track_price = ['BTCUSDT', 'ETHUSDT', 'DOGEUSDT'] #จำเป็นต้องมีการ sync กับ cach server อยู่เสมอดังนั้นค่านี้ควรดึงมาจาก database ด้วยการกด sync

#Database
mongodb_url = f"mongodb+srv://admin:lGqcI0m7LDYijdZG@cluster0.suk86zy.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"

#Cach Database
REDIS_HOST = 'redis-16692.c84.us-east-1-2.ec2.redns.redis-cloud.com'
REDIS_PORT = 16692
REDIS_PASSWORD = 'esnR4WeNvSGUvlygaLlBQvdSA19u05to'
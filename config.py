api_key = 'cos73h05s3oxvSK2u7YG2k0mIiu5npSVIXTdyIXXUVNJQOKbRybPNlGOeZNvunVG'
api_secret = 'Zim1iiECBaYdtx3rVlN5mpQ05iQWRXDXU0EBW8LmQW8Ns2X07HhKfIs4Kj3PLzgO'

"""api_key = '6041331240427dbbf26bd671beee93f6686b57dde4bde5108672963fad02bf2e'
api_secret = '560764a399e23e9bc5e24d041bd3b085ee710bf08755d26ff4822bfd9393b11e'"""

# Default settings
TP_LEVELS = {
    'TP1': {'id': 'tp1', 'size': '30%', 'target_atr': 1, 'move_sl_to_prev_level': True},
    'TP2': {'id': 'tp2', 'size': '35%', 'target_atr': 2, 'move_sl_to_prev_level': True},
    'TP3': {'id': 'tp3', 'size': 'MAX', 'target_atr': 3.5, 'move_sl_to_prev_level': True}
}

DEFAULT_CONFIG = {
    'timeframe': '4h',
    'entry_amount': '50$',
    'rsi_period': {
        'rsi_period_min': 7,
        'rsi_period_max': 14,
        'use_dynamic_period': True,
        'atr': {
            'length1': 4,
            'length2': 200,
            "length_tp": 7,
            "weight_percent": 50,
            'max_percent': 75,
            'min_percent': 10,
        }
    },
    'rsi_overbought': 68,
    'rsi_oversold': 32,
    'fix_stoploss': 4,
    'take_profits': {
        'use_dynamic_tp': True,
        'average_with_entry': 50,
        'levels': list(TP_LEVELS.values())
    },
    'martingale': {
        'enabled': True,
        'max_multiplier': 3.0,
        'step': 0.5,
        'reset_on_win': True
    }
}

# Trading pairs configuration
TRADING_CONFIG = [
    {**DEFAULT_CONFIG, 'symbol': 'ADAUSDT'},
    {**DEFAULT_CONFIG, 'symbol': 'XRPUSDT'},
    {**DEFAULT_CONFIG, 'symbol': 'BCHUSDT'},
    {**DEFAULT_CONFIG, 'symbol': 'SUIUSDT'},
    {**DEFAULT_CONFIG, 'symbol': 'DOGEUSDT'},
    {**DEFAULT_CONFIG, 'symbol': 'WIFUSDT'}
]

"""{**DEFAULT_CONFIG, 'symbol': 'DOGEUSDT',
     'take_profits': {
            'move_sl_to_entry_at_tp1': False,
            'levels': [  # ปรับ TP levels เฉพาะ
                {'id': 'tp1', 'size': 'MAX', 'target_atr': 1},
            ]
        }
    }"""

PRICE_CHANGE_THRESHOLD = 0.00225  # 0.1%
PRICE_INCREASE = 1 + PRICE_CHANGE_THRESHOLD  # 1.001
PRICE_DECREASE = 1 - PRICE_CHANGE_THRESHOLD  # 0.999
PRICE_CHANGE_MAXPERCENT = 2
MAX_CANDLES_TO_FETCH = 5
MIN_CANDLES_TO_FETCH = 3
MIN_NOTIONAL = 20 

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

#Database
"""mongodb_url = f"mongodb+srv://admin:lGqcI0m7LDYijdZG@cluster0.suk86zy.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"

#Cach Database
REDIS_HOST = 'redis-16692.c84.us-east-1-2.ec2.redns.redis-cloud.com'
REDIS_PORT = 16692
REDIS_PASSWORD = 'esnR4WeNvSGUvlygaLlBQvdSA19u05to'"""
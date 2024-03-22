import ccxt.async_support as ccxt
from config import default_testnet as testnet

async def get_position_mode(api_key, api_secret, symbol):
    exchange = ccxt.binance({
        'apiKey': api_key,
        'secret': api_secret,
        'enableRateLimit': True,
        'options': {
            'defaultType': 'future',
        },
    })

    exchange.set_sandbox_mode(testnet)

    positions = await exchange.fetch_positions()

    await exchange.close()

    if positions:
        for position in positions:
            if position['info']['symbol'] == symbol:
                if position['info']['positionSide'] == 'BOTH':
                    return 'oneway'
                else:
                    return 'hedge'
    return 'oneway'
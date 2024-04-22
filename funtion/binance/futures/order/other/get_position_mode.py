import ccxt.async_support as ccxt
from config import default_testnet as testnet
from funtion.binance.futures.system.create_future_exchange import create_future_exchange

async def get_position_mode(api_key, api_secret, symbol):
    exchange = await create_future_exchange(api_key, api_secret)

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
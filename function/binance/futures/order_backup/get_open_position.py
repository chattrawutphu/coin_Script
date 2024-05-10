from binance.client import Client


def get_open_position(api_key, api_secret, symbol):
    client = Client(api_key, api_secret)
    positions = client.futures_position_information(symbol=symbol)

    for position in positions:
        if float(position['positionAmt']) != 0:
            return position
    return None
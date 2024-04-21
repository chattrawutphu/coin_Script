import ast
import json
import os
import ccxt

# ฟังก์ชั่นนี้เป็นการ อัพเดทข้อมูล pricePrecision ของ symbol ทั้งหมด ไปยังตัวแปรชื่อ symbol_data ในไฟล์ config.py

def update_symbol_data(filtered_data):
    try:
        with open('config.py', 'r') as config_file:
            lines = config_file.readlines()
    except FileNotFoundError:
        lines = []

    symbol_data_index = None
    for i, line in enumerate(lines):
        if 'symbol_data' in line:
            symbol_data_index = i
            break

    if symbol_data_index is not None:
        symbol_data = ast.literal_eval(lines[symbol_data_index].split('=')[1].strip())
    else:
        symbol_data = []

    symbol_data = filtered_data

    symbol_data_str = json.dumps(symbol_data, separators=(',', ':'))
    if symbol_data_index is not None:
        lines[symbol_data_index] = f"symbol_data = {symbol_data_str}{os.linesep}"
    else:
        lines.append(f"symbol_data = {symbol_data_str}{os.linesep}")

    with open('config.py', 'w') as config_file:
        config_file.writelines(lines)





exchange = ccxt.binance({
    'apiKey': '6041331240427dbbf26bd671beee93f6686b57dde4bde5108672963fad02bf2e',
    'secret': '560764a399e23e9bc5e24d041bd3b085ee710bf08755d26ff4822bfd9393b11e',
    'enableRateLimit': True,
})
exchange.set_sandbox_mode(True)

data = exchange.fetch_markets()

filtered_data = []
for item in data:
    if item.get("info", {}).get("contractType") == "PERPETUAL":
        filtered_item = {
            "id": item["id"],
            "precision": item["precision"],
            "info": {
                "pricePrecision": item["info"]["pricePrecision"],
                "quantityPrecision": item["info"]["quantityPrecision"]
            }
        }
        filtered_data.append(filtered_item)
#print(filtered_data)
#with open('result.json', 'w') as f:
#    json.dump(filtered_data, f, indent=4)

update_symbol_data(filtered_data)
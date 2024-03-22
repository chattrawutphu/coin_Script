import json
import ccxt

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
print(filtered_data)
with open('result.json', 'w') as f:
    json.dump(filtered_data, f, indent=4)

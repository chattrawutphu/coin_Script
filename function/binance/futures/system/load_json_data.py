import json
import os

async def load_json_data(filepath, ismake=True):
    if os.path.exists(filepath):
        with open(filepath, 'r') as file:
            return json.load(file)
    elif ismake:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w') as file:
            json.dump({}, file)
    return {}
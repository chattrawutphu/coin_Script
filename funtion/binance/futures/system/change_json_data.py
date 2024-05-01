import json
import os

async def change_json_data(filepath, data,  ismake=True):
    if os.path.exists(filepath):
        with open(filepath, 'w') as file:
            json.dump(data, file, indent=4)
    elif ismake:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w') as file:
            json.dump([data], file, indent=4)  # เขียนข้อมูล JSON ใหม่เป็นลิสต์ที่มีข้อมูลเดียว
    else:
        raise FileNotFoundError("File not found and ismake is False.")
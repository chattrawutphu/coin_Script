import json
import os

async def add_json_data(filepath, data, ismake=True):
    if os.path.exists(filepath):
        with open(filepath, 'r') as file:
            json_data = json.load(file)
            json_data.append(data)  # เพิ่มข้อมูลใหม่เข้าไปในลิสต์ข้อมูล JSON
            with open(filepath, 'w') as file:
                json.dump(json_data, file, indent=4)  # เขียนข้อมูล JSON กลับไปยังไฟล์
    elif ismake:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w') as file:
            json.dump([data], file, indent=4)  # เขียนข้อมูล JSON ใหม่เป็นลิสต์ที่มีข้อมูลเดียว
    else:
        raise FileNotFoundError("File not found and ismake is False.")
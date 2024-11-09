"""import ssl
import ccxt.async_support as ccxt
from config import default_testnet as testnet
from config import mongodb_url
from function.create_mongodb_client import create_mongodb_client
from function.message import message

client = create_mongodb_client(mongodb_url)
db = client['coinscript']
logs_collection = db['user_position_mode']

async def get_position_mode(api_key, api_secret):
    user_data = await logs_collection.find_one({"api_key": api_key})
    if user_data:
        position_mode = user_data["position_mode"]
        return position_mode
    else:
        await save_position_mode(api_key, api_secret)
        return "oneway"  # สำหรับกรณีที่ไม่พบข้อมูล ให้สร้างใหม่และตั้งค่าเป็น "oneway"

async def save_position_mode(api_key, api_secret):
    data = {
        "api_key": api_key,
        "api_secret": api_secret,
        "position_mode": "oneway"
    }
    message("Test", "ไม่พบ user ทำการสร้างใหม่", "yellow")
    await logs_collection.insert_one(data)

async def change_position_mode(api_key, api_secret):
    user_data = await logs_collection.find_one({"api_key": api_key})
    if user_data:
        position_mode = user_data["position_mode"]
        new_position_mode = "hedge" if position_mode == "oneway" else "oneway"
        await logs_collection.update_one({"api_key": api_key}, {"$set": {"position_mode": new_position_mode}})
    else:
        await save_position_mode(api_key, api_secret)"""

import json
import os
import asyncio
from pathlib import Path

from function.message import message

# กำหนด path ของไฟล์ JSON
JSON_FILE_PATH = "json/user_position_mode.json"

# สร้างโฟลเดอร์ json ถ้ายังไม่มี
os.makedirs("json", exist_ok=True)

async def load_json_data():
    """โหลดข้อมูลจากไฟล์ JSON และตรวจสอบโครงสร้างข้อมูล"""
    try:
        if os.path.exists(JSON_FILE_PATH):
            with open(JSON_FILE_PATH, 'r') as file:
                data = json.load(file)
                # ถ้าข้อมูลเป็น list ให้แปลงเป็น dict
                if isinstance(data, list):
                    return {item["api_key"]: item for item in data} if data else {}
                return data
        return {}
    except json.JSONDecodeError:
        return {}

async def save_json_data(data):
    """บันทึกข้อมูลลงไฟล์ JSON"""
    # แปลง dict เป็น list ก่อนบันทึก
    data_list = list(data.values()) if isinstance(data, dict) else data
    with open(JSON_FILE_PATH, 'w') as file:
        json.dump(data_list, file, indent=4)

async def get_position_mode(api_key, api_secret):
    """ดึงข้อมูล position mode ของ user"""
    try:
        data = await load_json_data()
        if api_key in data:
            return data[api_key]["position_mode"]
        else:
            await save_position_mode(api_key, api_secret)
            return "oneway"
    except Exception as e:
        print(f"Error in get_position_mode: {str(e)}")
        await save_position_mode(api_key, api_secret)
        return "oneway"

async def save_position_mode(api_key, api_secret):
    """บันทึกข้อมูล position mode ใหม่"""
    try:
        data = await load_json_data()
        # ถ้าไม่มีข้อมูลเลย ให้สร้าง dict ใหม่
        if not isinstance(data, dict):
            data = {}
        
        data[api_key] = {
            "api_key": api_key,
            "api_secret": api_secret,
            "position_mode": "oneway"
        }
        message("Test", "ไม่พบ user ทำการสร้างใหม่", "yellow")
        await save_json_data(data)
    except Exception as e:
        print(f"Error in save_position_mode: {str(e)}")
        # ในกรณีที่เกิดข้อผิดพลาด ให้สร้างข้อมูลใหม่ทั้งหมด
        data = {
            api_key: {
                "api_key": api_key,
                "api_secret": api_secret,
                "position_mode": "oneway"
            }
        }
        await save_json_data(data)

async def change_position_mode(api_key, api_secret):
    """เปลี่ยน position mode ระหว่าง oneway และ hedge"""
    try:
        data = await load_json_data()
        if api_key in data:
            current_mode = data[api_key]["position_mode"]
            new_mode = "hedge" if current_mode == "oneway" else "oneway"
            data[api_key]["position_mode"] = new_mode
            await save_json_data(data)
        else:
            await save_position_mode(api_key, api_secret)
    except Exception as e:
        print(f"Error in change_position_mode: {str(e)}")
        await save_position_mode(api_key, api_secret)
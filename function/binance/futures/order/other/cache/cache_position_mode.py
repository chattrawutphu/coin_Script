import json
import ccxt.async_support as ccxt
from config import default_testnet as testnet
from function.binance.futures.system.add_json_data import add_json_data
from function.binance.futures.system.change_json_data import change_json_data
from function.binance.futures.system.load_json_data import load_json_data
from function.message import message

async def get_cache_position_mode(api_key, api_secret):
    data = await load_json_data("json/user_position_mode.json")

    for user_data in data:  # วนลูปผ่านข้อมูลของทุก user
        if api_key == user_data["api_key"]:
            position_mode = user_data["position_mode"]
            message("Test", f"position_mode {position_mode}", "yellow")
            return position_mode
    
    # หากไม่พบ api_key ในข้อมูล
    await save_cache_position_mode(api_key, api_secret)
  
async def save_cache_position_mode(api_key, api_secret):
    data = {
        "api_key": api_key,
        "api_secret": api_secret,
        "position_mode": "oneway"
    }
    message("Test", "ไม่พบ user ทำการสร้างใหม่", "yellow")
    await add_json_data("json/user_position_mode.json", data)
    return data["position_mode"]


async def change_cache_position_mode(api_key, api_secret):
    data = await load_json_data("json/user_position_mode.json")

    for user_data in data:  # วนลูปผ่านข้อมูลของทุก user
        if api_key == user_data["api_key"]:
            position_mode = user_data["position_mode"]
            new_position_mode = "hedge" if position_mode == "oneway" else "oneway"
            user_data['position_mode'] = new_position_mode
            await change_json_data("json/user_position_mode.json", data)
            return  # เมื่อทำการเปลี่ยนแปลงข้อมูลเสร็จแล้วให้จบฟังก์ชันทันที

    # ถ้าไม่พบ api_key ในข้อมูล ให้ทำการบันทึกข้อมูลใหม่และเปลี่ยนแปลงข้อมูล JSON
    await save_cache_position_mode(api_key, api_secret)
    await change_json_data("json/user_position_mode.json", data)

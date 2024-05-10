import ssl
import ccxt.async_support as ccxt
from config import default_testnet as testnet
from config import mongodb_url
from function.create_mongodb_client import create_mongodb_client
from function.message import message

client = create_mongodb_client(mongodb_url)
db = client['coinscript']
logs_collection = db['user_position_mode']

async def get_cache_position_mode(api_key, api_secret):
    user_data = await logs_collection.find_one({"api_key": api_key})
    if user_data:
        position_mode = user_data["position_mode"]
        message("Test", f"position_mode {position_mode}", "yellow")
        return position_mode
    else:
        await save_cache_position_mode(api_key, api_secret)
        return "oneway"  # สำหรับกรณีที่ไม่พบข้อมูล ให้สร้างใหม่และตั้งค่าเป็น "oneway"

async def save_cache_position_mode(api_key, api_secret):
    data = {
        "api_key": api_key,
        "api_secret": api_secret,
        "position_mode": "oneway"
    }
    message("Test", "ไม่พบ user ทำการสร้างใหม่", "yellow")
    await logs_collection.insert_one(data)

async def change_cache_position_mode(api_key, api_secret):
    user_data = await logs_collection.find_one({"api_key": api_key})
    if user_data:
        position_mode = user_data["position_mode"]
        new_position_mode = "hedge" if position_mode == "oneway" else "oneway"
        await logs_collection.update_one({"api_key": api_key}, {"$set": {"position_mode": new_position_mode}})
    else:
        await save_cache_position_mode(api_key, api_secret)
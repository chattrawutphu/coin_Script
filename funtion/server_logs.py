import os
import json
from datetime import datetime

from funtion.message import message

def save_server_logs(api_key, api_secret, log_type, log_level, catagory, sub_catagory, text, secondary_text="", show_message=False):
    # สร้างโฟลเดอร์เก็บ logs หากยังไม่มี
    timestamp = datetime.now().timestamp()
    logs_folder = os.path.join("json", "server_logs", api_key)
    if not os.path.exists(logs_folder):
        os.makedirs(logs_folder)

    # สร้างชื่อไฟล์ JSON จาก timestamp
    date_str = datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d")
    filename = os.path.join(logs_folder, f"{date_str}.json")

    # สร้างโครงสร้างข้อมูล log
    log_entry = {
        "timestamp": timestamp,
        "log_type": log_type,
        "log_level": log_level,
        "catagory": catagory,
        "sub_catagory": sub_catagory,
        "text": text,
        "secondary_text" : secondary_text,
        "api_key": api_key,
        "api_secret": api_secret
    }

    # อ่านข้อมูล logs จากไฟล์ JSON (หากมี)
    logs = []
    if os.path.exists(filename):
        with open(filename, 'r') as file:
            logs = json.load(file)

    # เพิ่ม log ใหม่ลงในรายการ logs
    logs.append(log_entry)

    # เขียนข้อมูล logs ลงในไฟล์ JSON
    with open(filename, 'w') as file:
        json.dump(logs, file, indent=4)
    
    if show_message == True:
        if log_type == "success": color = "cyan"
        if log_type == "warning": color = "yellow"
        else: color = "white"
        message("",f"{text}",color)

# # ตัวอย่างการใช้งาน
# api_key = "example_key"
# api_secret = "example_secret"
# log_type = "server"
# log_level = "info"
# catagory = "Server started"
# sub_catagory = "Server started"
# text = "The server has been started successfully."

# save_server_logs(api_key, api_secret, log_type, log_level, title, text)

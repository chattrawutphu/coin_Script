import os
import json
from datetime import datetime
from config import default_show_message, default_log_secondary_language, mongodb_url
from function.create_mongodb_client import create_mongodb_client

from function.message import message

# MongoDB client setup
"""client = create_mongodb_client(mongodb_url)
db = client['log_database']  # Adjust the database name as necessary
logs_collection = db['logs']
from config import default_log_database

async def save_server_logs(api_key, api_secret, log_type, log_level, catagory, sub_catagory, text, secondary_text=""):
    # Create logs document
    if default_log_database == True:
        timestamp = datetime.now().timestamp()
        log_entry = {
            "timestamp": timestamp,
            "log_type": log_type,
            "log_level": log_level,
            "catagory": catagory,
            "sub_catagory": sub_catagory,
            "text": text,
            "secondary_text": secondary_text,
            "api_key": api_key,
            "api_secret": api_secret
        }

        # Insert log entry into MongoDB
        await logs_collection.insert_one(log_entry)

    # Display message if configured
    if default_show_message[int(log_level) - 1]:
        color = "white"  # Default color
        if log_type == "success":
            color = "green"
        elif log_type == "warning":
            color = "yellow"

        if not default_log_secondary_language:
            message("", text, color)
        else:
            message("", secondary_text, color)"""

#สำหรับใช้ไฟล์ json แทน database
# async def save_server_logs(api_key, api_secret, log_type, log_level, catagory, sub_catagory, text, secondary_text=""):
#     # Create logs folder if it doesn't exist
#     timestamp = datetime.now().timestamp()
#     logs_folder = os.path.join("json", "server_logs", api_key)
#     if not os.path.exists(logs_folder):
#         os.makedirs(logs_folder)

#     # Create JSON filename from timestamp
#     date_str = datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d")
#     filename = os.path.join(logs_folder, f"{date_str}.json")

#     # Construct log entry
#     log_entry = {
#         "timestamp": timestamp,
#         "log_type": log_type,
#         "log_level": log_level,
#         "catagory": catagory,
#         "sub_catagory": sub_catagory,
#         "text": text,
#         "secondary_text": secondary_text,
#         "api_key": api_key,
#         "api_secret": api_secret
#     }

#     # Read existing logs from JSON file (if exists)
#     logs = []
#     if os.path.exists(filename):
#         async with aiofiles.open(filename, 'r', encoding='utf-8') as file:
#             content = await file.read()
#             logs = json.loads(content)

#     # Add new log to the list
#     logs.append(log_entry)

#     # Write logs to JSON file
#     async with aiofiles.open(filename, 'w', encoding='utf-8') as file:
#         await file.write(json.dumps(logs, indent=4, ensure_ascii=False))

#     # Display message if configured
#     if default_show_message[int(log_level) - 1]:
#         color = "white"  # Default color
#         if log_type == "success":
#             color = "green"
#         elif log_type == "warning":
#             color = "yellow"
        
#         if not default_log_secondary_language:
#             message("", text, color)
#         else:
#             message("", secondary_text, color)

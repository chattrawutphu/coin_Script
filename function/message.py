import os
import json
from datetime import datetime

# เพิ่มตัวแปร global สำหรับเก็บข้อความล่าสุด
last_message_content = None

def ensure_log_directory():
    """สร้างโฟลเดอร์ message_logs ถ้ายังไม่มี"""
    if not os.path.exists('json/message_logs'):
        os.makedirs('json/message_logs')

def save_message_to_json(symbol, message_data):
    """บันทึกข้อความลงในไฟล์ JSON แยกตามเหรียญ"""
    ensure_log_directory()
    filename = f'json/message_logs/{symbol}.json'
    
    try:
        if os.path.exists(filename):
            with open(filename, 'r', encoding='utf-8') as f:
                messages = json.load(f)
        else:
            messages = []
            
        messages.append(message_data)
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(messages, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving message to JSON: {str(e)}")

# เพิ่มตัวแปร global สำหรับเก็บข้อความล่าสุดแต่ละ symbol
last_message_content = {}

def message(symbol='', message='', color='white'):
    global last_message_content
    
    current_time = datetime.now().strftime("%H:%M:%S")
    current_date = datetime.now().strftime("%Y-%m-%d")
    
    color_code = {
        'black': '\033[0;30m',
        'red': '\033[0;31m',
        'green': '\033[0;32m',
        'yellow': '\033[0;33m',
        'blue': '\033[0;34m',
        'magenta': '\033[0;35m',
        'cyan': '\033[0;36m',
        'white': '\033[0;37m',
    }
    reset_code = '\033[0m'

    if color in color_code:
        color_prefix = color_code[color]
    else:
        color_prefix = ''

    # สร้างข้อความที่จะแสดง
    if symbol != "":
        current_message = f"[{symbol}] {message}"
    else:
        current_message = message

    # ตรวจสอบข้อความล่าสุดสำหรับ symbol นี้
    last_message = last_message_content.get(symbol, "")

    # แสดงข้อความเฉพาะเมื่อไม่ซ้ำกับข้อความก่อนหน้า
    if current_message != last_message:
        if symbol != "":
            print(f"[{current_time}][{current_date}][{symbol}] {color_prefix}{message}{reset_code}")
        else:
            print(f"[{current_time}][{current_date}] {color_prefix}{message}{reset_code}")
            
        # บันทึกข้อความลง JSON
        message_data = {
            'timestamp': f"{current_date} {current_time}",
            'date': current_date,
            'time': current_time,
            'symbol': symbol,
            'message': message,
            'color': color
        }
        
        if symbol:  # บันทึกเฉพาะข้อความที่มี symbol
            save_message_to_json(symbol, message_data)
        
        # อัพเดทข้อความล่าสุดสำหรับ symbol นี้
        last_message_content[symbol] = current_message

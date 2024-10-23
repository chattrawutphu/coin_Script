"""from datetime import datetime

def message(symbol='', message='', color='white'):
    current_time = datetime.now().strftime("%H:%M:%S")
    current_date = datetime.now().strftime("%Y-%m-%d")  # ปรับรูปแบบวันที่และเวลาตามต้องการ
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

    if symbol != "":
        print(f"[{current_time}][{current_date}][{symbol}] {color_prefix}{message}{reset_code}")
    else:
        print(f"[{current_time}][{current_date}] {color_prefix}{message}{reset_code}")"""

from datetime import datetime

# เพิ่มตัวแปร global สำหรับเก็บข้อความล่าสุด
last_message_content = None

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

    # แสดงข้อความเฉพาะเมื่อไม่ซ้ำกับข้อความก่อนหน้า
    if current_message != last_message_content:
        if symbol != "":
            print(f"[{current_time}][{current_date}][{symbol}] {color_prefix}{message}{reset_code}")
        else:
            print(f"[{current_time}][{current_date}] {color_prefix}{message}{reset_code}")
        
        # อัพเดทข้อความล่าสุด
        last_message_content = current_message
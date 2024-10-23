# utils/retry_utils.py
import asyncio
from functools import wraps

from function.message import message

def retry_with_backoff(max_retries=3, initial_delay=1, max_delay=60):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exception = None
            
            for retry in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if retry < max_retries - 1:
                        message(kwargs.get('symbol', ''), 
                            f"เกิดข้อผิดพลาด (พยายามอีกครั้งใน {delay} วินาที): {str(e)}", "yellow")
                        await asyncio.sleep(delay)
                        delay = min(delay * 2, max_delay)
                    else:
                        message(kwargs.get('symbol', ''), 
                            f"เกิดข้อผิดพลาดหลังจากลองซ้ำ {max_retries} ครั้ง: {str(e)}", "red")
            raise last_exception
        return wrapper
    return decorator

async def run_with_error_handling(main_func, symbol=''):
    restart_count = 0
    max_restarts = 5
    while restart_count < max_restarts:
        try:
            await main_func()
        except KeyboardInterrupt:
            message(symbol, "โปรแกรมถูกหยุดโดยผู้ใช้", "yellow")
            break
        except Exception as e:
            restart_count += 1
            message(symbol, f"เกิดข้อผิดพลาด (ครั้งที่ {restart_count}/{max_restarts}): {str(e)}", "red")
            
            if restart_count < max_restarts:
                wait_time = 60
                message(symbol, f"รอ {wait_time} วินาทีก่อนเริ่มใหม่...", "yellow")
                await asyncio.sleep(wait_time)
                message(symbol, "เริ่มการทำงานใหม่...", "green")
            else:
                message(symbol, "เกินจำนวนครั้งที่กำหนดในการ restart โปรแกรมจะหยุดทำงาน", "red")
                break
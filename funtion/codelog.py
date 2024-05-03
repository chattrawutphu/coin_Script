from config import default_testnet as default_show_message

from funtion.message import message
from funtion.server_logs import save_server_logs

def codelog(api_key, api_secret, id, param1="", param2="", param3="", param4="", param5=""):
    if id=="c1001t-en0":
        save_server_logs(api_key, api_secret, "success", "4", "condition result", "price", f"condition {param1} price {param3} {param2} is success", f"เช็คเงื่อนไข {param1} ราคา {param3} {param2} ถูกต้อง")
    elif id=="c1001f":
        save_server_logs(api_key, api_secret, "warning", "4", "condition result", "price", f"condition {param1} price {param3} {param2} is fail", f"เช็คเงื่อนไข {param1} ราคา {param3} {param2} ไม่ถูกต้อง")
    elif id=="c1002t":
        save_server_logs(api_key, api_secret, "success", "4", "condition result", "balance", f"condition balance {param2} {param1}  is success", f"เช็คเงื่อนไข ยอดเงิน {param2} {param1} ถูกต้อง")
    elif id=="c1002f":
        save_server_logs(api_key, api_secret, "warning", "4", "condition result", "balance", f"condition balance {param2} {param1}  is fail", f"เช็คเงื่อนไข ยอดเงิน {param2} {param1} ไม่ถูกต้อง")

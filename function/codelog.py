from funtion.message import message
from funtion.server_logs import save_server_logs

async def codelog(api_key, api_secret, id, param1="", param2="", param3="", param4="", param5=""):
    if id == "c1001t":
        await save_server_logs(api_key, api_secret, "success", "4", "condition result", "price", f"Condition {param1} price {param3} {param2} is success", f"เช็คเงื่อนไข {param1} ราคา {param3} {param2} ถูกต้อง")
    elif id == "c1001f":
        await save_server_logs(api_key, api_secret, "warning", "4", "condition result", "price", f"Condition {param1} price {param3} {param2} is fail", f"เช็คเงื่อนไข {param1} ราคา {param3} {param2} ไม่ถูกต้อง")
    elif id == "c1002t":
        await save_server_logs(api_key, api_secret, "success", "4", "condition result", "balance", f"Condition balance {param2} {param1} is success", f"เช็คเงื่อนไข ยอดเงิน {param2} {param1} ถูกต้อง")
    elif id == "c1002f":
        await save_server_logs(api_key, api_secret, "warning", "4", "condition result", "balance", f"Condition balance {param2} {param1} is fail", f"เช็คเงื่อนไข ยอดเงิน {param2} {param1} ไม่ถูกต้อง")
    elif id == "c1003t":
        await save_server_logs(api_key, api_secret, "success", "4", "condition result", "position", f"Condition position {param1} is success", f"เช็คเงื่อนไข position {param1} ถูกต้อง")
    elif id == "c1003f":
        await save_server_logs(api_key, api_secret, "warning", "4", "condition result", "position", f"Condition position {param1} is fail", f"เช็คเงื่อนไข position {param1} ไม่ถูกต้อง")
    elif id == "s1001t":
        await save_server_logs(api_key, api_secret, "success", "5", "system result", "server", f"Server status condition is success", f"เช็คสถานะ server ถูกต้อง")
    
    
    elif id == "s1001f":
        await save_server_logs(api_key, api_secret, "warning", "5", "system result", "server", f"Server status condition is fail", f"เช็คสถานะ server ไม่ถูกต้อง")
    elif id == "s1002t":
        await save_server_logs(api_key, api_secret, "success", "5", "system result", "api", f"API status condition is success", f"เช็คสถานะ api ถูกต้อง")
    elif id == "s1002f":
        await save_server_logs(api_key, api_secret, "warning", "5", "system result", "api", f"API status condition is fail", f"เช็คสถานะ api ไม่ถูกต้อง")
    else:
        message("", f"log id {id} is wrong!!!", "red")

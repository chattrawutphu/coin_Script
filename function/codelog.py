
from function.message import message
from function.server_logs import save_server_logs

async def codelog(api_key, api_secret, id, *params):
    
    log_messages = {
        "c1001t": ("success", "4", "condition result", "price", f"Condition {params[0]} price {params[2]} {params[1]} is success", f"เช็คเงื่อนไข {params[0]} ราคา {params[2]} {params[1]} ถูกต้อง") if len(params) >= 3 else None,
        "c1001f": ("warning", "4", "condition result", "price", f"Condition {params[0]} price {params[2]} {params[1]} is fail", f"เช็คเงื่อนไข {params[0]} ราคา {params[2]} {params[1]} ไม่ถูกต้อง") if len(params) >= 3 else None,
        "c1002t": ("success", "4", "condition result", "balance", f"Condition balance {params[1]} {params[0]} is success", f"เช็คเงื่อนไข ยอดเงิน {params[1]} {params[0]} ถูกต้อง") if len(params) >= 2 else None,
        "c1002f": ("warning", "4", "condition result", "balance", f"Condition balance {params[1]} {params[0]} is fail", f"เช็คเงื่อนไข ยอดเงิน {params[1]} {params[0]} ไม่ถูกต้อง") if len(params) >= 2 else None,
        "c1003t": ("success", "4", "condition result", "position", f"Condition position {params[0]} is success", f"เช็คเงื่อนไข position {params[0]} ถูกต้อง") if len(params) >= 1 else None,
        "c1003f": ("warning", "4", "condition result", "position", f"Condition position {params[0]} is fail", f"เช็คเงื่อนไข position {params[0]} ไม่ถูกต้อง") if len(params) >= 1 else None,
        
        "s1001t": ("success", "5", "system result", "server", f"Server status condition is success", f"เช็คสถานะ server ถูกต้อง"),
        "s1001f": ("warning", "5", "system result", "server", f"Server status condition is fail", f"เช็คสถานะ server ไม่ถูกต้อง"),
        "s1002t": ("success", "5", "system result", "api", f"API status condition is success", f"เช็คสถานะ api ถูกต้อง"),
        "s1002f": ("warning", "5", "system result", "api", f"เช็คสถานะ api ไม่ถูกต้อง"),
        
        "a1001t": ("success", "2", "action result", "order", f"Action {params[1]} {params[4]} {params[0]} price {params[2]} amount {params[3]} is success", f"คำสั่ง {params[1]} {params[4]} {params[0]} ราคา {params[2]} จำนวน {params[3]} สำเร็จ") if len(params) >= 5 else None,
        "a1001f": ("warning", "2", "action result", "order", f"Action {params[1]} {params[4]} {params[0]} price {params[2]} amount {params[3]} is fail", f"คำสั่ง {params[1]} {params[4]} {params[0]} ราคา {params[2]} จำนวน {params[3]} ไม่สำเร็จ") if len(params) >= 5 else None
    }
    
    if log_messages[id]:
        await save_server_logs(api_key, api_secret, *log_messages[id])
    else:
        message("", f"log id {id} is wrong!!!", "red")



# from function.message import message
# from function.server_logs import save_server_logs
# from config import default_log_database

# async def codelog(api_key, api_secret, id, param1="", param2="", param3="", param4="", param5=""):
#     # if default_log_database == False: return 0
#     if id == "c1001t":
#         await save_server_logs(api_key, api_secret, "success", "4", "condition result", "price", f"Condition {param1} price {param3} {param2} is success", f"เช็คเงื่อนไข {param1} ราคา {param3} {param2} ถูกต้อง")
#     elif id == "c1001f":
#         await save_server_logs(api_key, api_secret, "warning", "4", "condition result", "price", f"Condition {param1} price {param3} {param2} is fail", f"เช็คเงื่อนไข {param1} ราคา {param3} {param2} ไม่ถูกต้อง")
#     elif id == "c1002t":
#         await save_server_logs(api_key, api_secret, "success", "4", "condition result", "balance", f"Condition balance {param2} {param1} is success", f"เช็คเงื่อนไข ยอดเงิน {param2} {param1} ถูกต้อง")
#     elif id == "c1002f":
#         await save_server_logs(api_key, api_secret, "warning", "4", "condition result", "balance", f"Condition balance {param2} {param1} is fail", f"เช็คเงื่อนไข ยอดเงิน {param2} {param1} ไม่ถูกต้อง")
#     elif id == "c1003t":
#         await save_server_logs(api_key, api_secret, "success", "4", "condition result", "position", f"Condition position {param1} is success", f"เช็คเงื่อนไข position {param1} ถูกต้อง")
#     elif id == "c1003f":
#         await save_server_logs(api_key, api_secret, "warning", "4", "condition result", "position", f"Condition position {param1} is fail", f"เช็คเงื่อนไข position {param1} ไม่ถูกต้อง")
    
#     elif id == "s1001t":
#         await save_server_logs(api_key, api_secret, "success", "5", "system result", "server", f"Server status condition is success", f"เช็คสถานะ server ถูกต้อง")
#     elif id == "s1001f":
#         await save_server_logs(api_key, api_secret, "warning", "5", "system result", "server", f"Server status condition is fail", f"เช็คสถานะ server ไม่ถูกต้อง")
#     elif id == "s1002t":
#         await save_server_logs(api_key, api_secret, "success", "5", "system result", "api", f"API status condition is success", f"เช็คสถานะ api ถูกต้อง")
#     elif id == "s1002f":
#         await save_server_logs(api_key, api_secret, "warning", "5", "system result", "api", f"API status condition is fail", f"เช็คสถานะ api ไม่ถูกต้อง")
    
#     elif id == "a1001t":
#         await save_server_logs(api_key, api_secret, "success", "2", "action result", "order", f"Action {param2} {param5} {param1} price {param3} amount {param4} is success", f"คำสั่ง {param2} {param5} {param1} ราคา {param3} จำนวน {param4} สำเร็จ")
#     elif id == "a1001f":
#         await save_server_logs(api_key, api_secret, "warning", "2", "action result", "order", f"Action {param2} {param5} {param1} price {param3} amount {param4} is fail", f"คำสั่ง {param2} {param5} {param1} ราคา {param3} จำนวน {param4} ไม่สำเร็จ")
    
    
#     else:
#         message("", f"log id {id} is wrong!!!", "red")

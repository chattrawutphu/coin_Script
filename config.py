default_testnet = False
default_show_message = [ #ใช้สำหรับ โชว์ ข้อความแต่ละความสำคัญใน terminal
    True,
    True,
    True,
    True,
    True
]
default_log_secondary_language = False #server log เป็นภาษาไทย
default_log_database = False #ยอมรับให้เก็บข้อมูลลง database

symbols_track_price = ['BTCUSDT', 'ETHUSDT', 'DOGEUSDT'] #จำเป็นต้องมีการ sync กับ cach server อยู่เสมอดังนั้นค่านี้ควรดึงมาจาก database ด้วยการกด sync

#Database
mongodb_url = f"mongodb+srv://admin:lGqcI0m7LDYijdZG@cluster0.suk86zy.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"

#Cach Database
REDIS_HOST = 'redis-16692.c84.us-east-1-2.ec2.redns.redis-cloud.com'
REDIS_PORT = 16692
REDIS_PASSWORD = 'esnR4WeNvSGUvlygaLlBQvdSA19u05to'
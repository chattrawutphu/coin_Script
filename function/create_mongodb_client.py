import ssl
import motor.motor_asyncio as aiomotor

def create_mongodb_client(mongodb_url):
    return aiomotor.AsyncIOMotorClient(mongodb_url)
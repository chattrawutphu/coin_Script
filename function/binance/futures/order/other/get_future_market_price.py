import json
import asyncio
import websockets
from typing import Dict, Set, Optional
from datetime import datetime
import logging
from collections import defaultdict

class BinancePriceTracker:
    def __init__(self):
        self.ws_url = "wss://fstream.binance.com/ws"
        self.prices: Dict[str, float] = {}
        self.subscribed_symbols: Set[str] = set()
        self.websocket = None
        self.is_running = False
        self.callbacks = defaultdict(list)
        self.logger = self._setup_logger()
        self._lock = asyncio.Lock()
        self._last_update: Dict[str, datetime] = {}

    def _setup_logger(self):
        logger = logging.getLogger('BinancePriceTracker')
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger

    def subscribe_symbol(self, symbol: str):
        """สมัครติดตามราคาของเหรียญ"""
        clean_symbol = symbol.lower()
        self.subscribed_symbols.add(clean_symbol)
        if self.is_running:
            asyncio.create_task(self._send_subscription(clean_symbol))

    def unsubscribe_symbol(self, symbol: str):
        """ยกเลิกการติดตามราคาของเหรียญ"""
        clean_symbol = symbol.lower()
        self.subscribed_symbols.discard(clean_symbol)
        if self.is_running:
            asyncio.create_task(self._send_unsubscription(clean_symbol))

    def get_price(self, symbol: str) -> Optional[float]:
        """ดึงราคาล่าสุดของเหรียญ"""
        return self.prices.get(symbol.lower())

    def add_price_callback(self, symbol: str, callback):
        """เพิ่ม callback function เมื่อราคาเปลี่ยนแปลง"""
        self.callbacks[symbol.lower()].append(callback)

    async def start(self):
        """เริ่มการเชื่อมต่อ WebSocket และติดตามราคา"""
        if self.is_running:
            return

        self.is_running = True
        while self.is_running:
            try:
                async with websockets.connect(self.ws_url) as websocket:
                    self.websocket = websocket
                    self.logger.info("เชื่อมต่อ WebSocket สำเร็จ")

                    # สมัครติดตามราคาทุกเหรียญที่ต้องการ
                    for symbol in self.subscribed_symbols:
                        await self._send_subscription(symbol)

                    # ลูปหลักสำหรับรับข้อความ
                    while self.is_running:
                        try:
                            message = await websocket.recv()
                            await self._handle_message(json.loads(message))
                        except websockets.exceptions.ConnectionClosed:
                            self.logger.warning("การเชื่อมต่อ WebSocket ถูกปิด กำลังพยายามเชื่อมต่อใหม่...")
                            break
                        except Exception as e:
                            self.logger.error(f"เกิดข้อผิดพลาดในการจัดการข้อความ: {str(e)}")

            except Exception as e:
                self.logger.error(f"เกิดข้อผิดพลาดในการเชื่อมต่อ WebSocket: {str(e)}")
                if self.is_running:
                    self.logger.info("กำลังพยายามเชื่อมต่อใหม่ในอีก 5 วินาที...")
                    await asyncio.sleep(5)

    async def stop(self):
        """หยุดการเชื่อมต่อ WebSocket และการติดตามราคา"""
        self.is_running = False
        if self.websocket:
            await self.websocket.close()

    async def _send_subscription(self, symbol: str):
        """ส่งคำสั่งสมัครติดตามราคาเหรียญ"""
        if not self.websocket:
            return

        subscribe_message = {
            "method": "SUBSCRIBE",
            "params": [f"{symbol}@aggTrade"],
            "id": 1
        }
        await self.websocket.send(json.dumps(subscribe_message))

    async def _send_unsubscription(self, symbol: str):
        """ส่งคำสั่งยกเลิกการติดตามราคาเหรียญ"""
        if not self.websocket:
            return

        unsubscribe_message = {
            "method": "UNSUBSCRIBE",
            "params": [f"{symbol}@aggTrade"],
            "id": 1
        }
        await self.websocket.send(json.dumps(unsubscribe_message))

    async def _handle_message(self, message: dict):
        """จัดการข้อความที่ได้รับจาก WebSocket"""
        try:
            if 'e' in message and message['e'] == 'aggTrade':
                symbol = message['s'].lower()
                price = float(message['p'])
                
                async with self._lock:
                    self.prices[symbol] = price
                    self._last_update[symbol] = datetime.now()

                # เรียกใช้ callbacks สำหรับเหรียญนี้
                for callback in self.callbacks[symbol]:
                    try:
                        await callback(symbol, price)
                    except Exception as e:
                        self.logger.error(f"เกิดข้อผิดพลาดใน callback ของ {symbol}: {str(e)}")

        except Exception as e:
            self.logger.error(f"เกิดข้อผิดพลาดในการประมวลผลข้อความ: {str(e)}")

    def get_last_update_time(self, symbol: str) -> Optional[datetime]:
        """ดึงเวลาอัพเดทล่าสุดของเหรียญ"""
        return self._last_update.get(symbol.lower())

# Singleton instance
_price_tracker: Optional[BinancePriceTracker] = None

def get_price_tracker() -> BinancePriceTracker:
    """ดึงหรือสร้าง instance ของ price tracker"""
    global _price_tracker
    if _price_tracker is None:
        _price_tracker = BinancePriceTracker()
    return _price_tracker

async def get_future_market_price(api_key: str, api_secret: str, symbol: str) -> Optional[float]:
    """ดึงราคาตลาดล่าสุดของเหรียญโดยใช้ข้อมูลจาก WebSocket"""
    tracker = get_price_tracker()
    
    # แปลงชื่อเหรียญเป็นตัวพิมพ์เล็ก
    symbol = symbol.lower()
    
    # สมัครติดตามราคาถ้ายังไม่ได้สมัคร
    if symbol not in tracker.subscribed_symbols:
        tracker.subscribe_symbol(symbol)
        # เริ่ม tracker ถ้ายังไม่ได้เริ่ม
        if not tracker.is_running:
            asyncio.create_task(tracker.start())
        # รอข้อมูลราคาเริ่มต้น
        for _ in range(10):  # รอสูงสุด 1 วินาทีสำหรับข้อมูลเริ่มต้น
            await asyncio.sleep(0.1)
            if symbol in tracker.prices:
                break
    
    return tracker.get_price(symbol)
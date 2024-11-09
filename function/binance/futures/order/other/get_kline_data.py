import json
import asyncio
import pytz
import websockets
from typing import Dict, Set, Optional, List
from datetime import datetime
import logging
from collections import defaultdict, deque
from config import api_key, api_secret

from function.binance.futures.system.create_future_exchange import create_future_exchange

class KlineData:
    def __init__(self, data: dict):
        self.open_time = int(data['t'])  # Kline start time
        self.open = float(data['o'])     # Open price
        self.high = float(data['h'])     # High price
        self.low = float(data['l'])      # Low price
        self.close = float(data['c'])    # Close price
        self.volume = float(data['v'])   # Volume
        self.close_time = int(data['T']) # Kline close time
        self.is_closed = data['x']       # Is this kline closed?

    def to_ohlcv(self) -> list:
        """แปลงข้อมูลเป็นรูปแบบ OHLCV"""
        return [
            self.open_time,
            self.open,
            self.high,
            self.low,
            self.close,
            self.volume
        ]

class BinanceKlineTracker:
    def __init__(self, max_candles: int = 1000):
        self.ws_url = "wss://fstream.binance.com/ws"
        self.subscribed_pairs: Dict[str, Set[str]] = defaultdict(set)  # symbol -> set of timeframes
        self.klines: Dict[str, Dict[str, deque]] = defaultdict(lambda: defaultdict(lambda: deque(maxlen=max_candles)))
        self.websocket = None
        self.is_running = False
        self.callbacks = defaultdict(lambda: defaultdict(list))
        self.logger = self._setup_logger()
        self._lock = asyncio.Lock()
        self._initialized_pairs: Set[tuple] = set()  # เก็บคู่ symbol/timeframe ที่โหลดข้อมูลเริ่มต้นแล้ว
        self.local_tz = pytz.timezone('Asia/Bangkok')

    async def initialize_symbol_data(self, symbol: str, timeframe: str):
        """โหลดข้อมูลเริ่มต้นจาก API"""
        if (symbol, timeframe) in self._initialized_pairs:
            return

        try:
            # แก้ไขการแปลง symbol format
            exchange_symbol = symbol.upper()  # แปลงเป็นตัวพิมพ์ใหญ่
            if 'USDT' in exchange_symbol and '/USDT:USDT' not in exchange_symbol:
                exchange_symbol = exchange_symbol.replace('USDT', '/USDT:USDT')
            
            exchange = await create_future_exchange(api_key, api_secret)
            
            try:
                ohlcv = await exchange.fetch_ohlcv(exchange_symbol, timeframe, limit=100)
                
                if ohlcv and len(ohlcv) > 0:
                    async with self._lock:
                        for candle in ohlcv:
                            kline = KlineData({
                                't': candle[0],
                                'T': candle[0] + exchange.parse_timeframe(timeframe) * 1000 - 1,
                                'o': str(candle[1]),
                                'h': str(candle[2]),
                                'l': str(candle[3]),
                                'c': str(candle[4]),
                                'v': str(candle[5]),
                                'x': True
                            })
                            self.klines[symbol.lower()][timeframe].append(kline)
                    
                    self._initialized_pairs.add((symbol, timeframe))
                    #self.logger.info(f"โหลดข้อมูลเริ่มต้นสำหรับ {symbol} {timeframe} สำเร็จ")
                else:
                    self.logger.warning(f"ไม่สามารถโหลดข้อมูลเริ่มต้นสำหรับ {symbol} {timeframe}")

            except Exception as e:
                raise e
            finally:
                await exchange.close()

        except Exception as e:
            self.logger.error(f"เกิดข้อผิดพลาดในการโหลดข้อมูลเริ่มต้น {symbol} {timeframe}: {str(e)}")

    def _setup_logger(self):
        logger = logging.getLogger('BinanceKlineTracker')
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger

    async def subscribe(self, symbol: str, timeframe: str):
        """สมัครติดตามแท่งเทียนและโหลดข้อมูลเริ่มต้น"""
        clean_symbol = symbol.lower()
        self.subscribed_pairs[clean_symbol].add(timeframe)
        
        # โหลดข้อมูลเริ่มต้นก่อน
        await self.initialize_symbol_data(symbol, timeframe)
        
        # ถ้า websocket กำลังทำงาน ให้ส่งคำสั่งสมัครสมาชิก
        if self.is_running:
            await self._send_subscription(clean_symbol, timeframe)

    def unsubscribe(self, symbol: str, timeframe: str):
        """ยกเลิกการติดตามแท่งเทียนของเหรียญและ timeframe ที่ระบุ"""
        clean_symbol = symbol.lower()
        self.subscribed_pairs[clean_symbol].discard(timeframe)
        if self.is_running:
            asyncio.create_task(self._send_unsubscription(clean_symbol, timeframe))

    async def get_klines(self, symbol: str, timeframe: str, limit: int = None) -> List[list]:
        """ดึงข้อมูลแท่งเทียนล่าสุด"""
        clean_symbol = symbol.lower()
        async with self._lock:
            klines = list(self.klines[clean_symbol][timeframe])
            if limit:
                return [k.to_ohlcv() for k in klines[-limit:]]
            return [k.to_ohlcv() for k in klines]

    def add_kline_callback(self, symbol: str, timeframe: str, callback):
        """เพิ่ม callback function เมื่อได้รับข้อมูลแท่งเทียนใหม่"""
        clean_symbol = symbol.lower()
        self.callbacks[clean_symbol][timeframe].append(callback)

    async def start(self):
        """เริ่มการเชื่อมต่อ WebSocket และติดตามแท่งเทียน"""
        if self.is_running:
            return

        self.is_running = True
        try:
            while self.is_running:
                try:
                    async with websockets.connect(self.ws_url) as websocket:
                        self.websocket = websocket
                        #self.logger.info("เชื่อมต่อ WebSocket สำเร็จ")

                        # สมัครติดตามทุกคู่เหรียญและ timeframe
                        for symbol, timeframes in self.subscribed_pairs.items():
                            for timeframe in timeframes:
                                await self._send_subscription(symbol, timeframe)

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
        finally:
            self.websocket = None

    async def stop(self):
        """หยุดการเชื่อมต่อ WebSocket"""
        self.is_running = False
        if self.websocket:
            try:
                await self.websocket.close()
            except Exception as e:
                self.logger.error(f"เกิดข้อผิดพลาดในการปิด WebSocket: {str(e)}")
            finally:
                self.websocket = None

    async def _send_subscription(self, symbol: str, timeframe: str):
        """ส่งคำสั่งสมัครติดตามแท่งเทียน"""
        if not self.websocket:
            return

        subscribe_message = {
            "method": "SUBSCRIBE",
            "params": [f"{symbol}@kline_{timeframe}"],
            "id": 1
        }
        await self.websocket.send(json.dumps(subscribe_message))

    async def _send_unsubscription(self, symbol: str, timeframe: str):
        """ส่งคำสั่งยกเลิกการติดตามแท่งเทียน"""
        if not self.websocket:
            return

        unsubscribe_message = {
            "method": "UNSUBSCRIBE",
            "params": [f"{symbol}@kline_{timeframe}"],
            "id": 1
        }
        await self.websocket.send(json.dumps(unsubscribe_message))

    async def _handle_message(self, message: dict):
            try:
                if 'e' in message and message['e'] == 'kline':
                    symbol = message['s'].lower()
                    kline_data = message['k']
                    timeframe = kline_data['i']
                    
                    # แปลงเวลาเป็น local timezone
                    kline_data['t'] = datetime.fromtimestamp(
                        int(kline_data['t'])/1000, 
                        tz=pytz.UTC
                    ).astimezone(self.local_tz).timestamp() * 1000
                    
                    kline_data['T'] = datetime.fromtimestamp(
                        int(kline_data['T'])/1000, 
                        tz=pytz.UTC
                    ).astimezone(self.local_tz).timestamp() * 1000
                    
                    kline = KlineData(kline_data)
                    
                    async with self._lock:
                        # อัพเดทหรือเพิ่มแท่งเทียนใหม่
                        klines = self.klines[symbol][timeframe]
                        if not klines or klines[-1].open_time != kline.open_time:
                            klines.append(kline)
                        else:
                            klines[-1] = kline

                    # เรียกใช้ callbacks
                    for callback in self.callbacks[symbol][timeframe]:
                        try:
                            await callback(symbol, timeframe, kline)
                        except Exception as e:
                            self.logger.error(f"เกิดข้อผิดพลาดใน callback ของ {symbol} {timeframe}: {str(e)}")

            except Exception as e:
                self.logger.error(f"เกิดข้อผิดพลาดในการประมวลผลข้อความ: {str(e)}")

# Singleton instance
_kline_tracker: Optional[BinanceKlineTracker] = None

def get_kline_tracker() -> BinanceKlineTracker:
    """ดึงหรือสร้าง instance ของ kline tracker"""
    global _kline_tracker
    if _kline_tracker is None:
        _kline_tracker = BinanceKlineTracker()
    return _kline_tracker

async def fetch_ohlcv(symbol: str, timeframe: str, limit: int = None) -> List[list]:
    """ดึงข้อมูล OHLCV โดยใช้ WebSocket หรือ API"""
    tracker = get_kline_tracker()
    
    # แปลงชื่อเหรียญเป็นตัวพิมพ์เล็ก
    symbol = symbol.lower()
    
    # ถ้ายังไม่มีข้อมูล ให้สมัครและรอข้อมูลเริ่มต้น
    if timeframe not in tracker.subscribed_pairs[symbol]:
        # เปลี่ยนจาก tracker.subscribe เป็น await tracker.subscribe
        await tracker.subscribe(symbol, timeframe)
        if not tracker.is_running:
            asyncio.create_task(tracker.start())
        
        # รอให้โหลดข้อมูลเริ่มต้นเสร็จ
        for _ in range(20):  # รอนานขึ้นเพื่อให้แน่ใจว่าได้ข้อมูลครบ
            if (symbol, timeframe) in tracker._initialized_pairs:
                break
            await asyncio.sleep(0.1)
    
    return await tracker.get_klines(symbol, timeframe, limit)
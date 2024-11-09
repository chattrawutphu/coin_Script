import os
import json
from datetime import datetime
from pathlib import Path
import math

class MessageLogger:
    MESSAGES_PER_FILE = 20
    
    def __init__(self):
        self.base_dir = Path('json/message_logs')
        self.last_message_content = {}
        
    def ensure_directory(self, symbol: str, date: str):
        """Ensure the directory structure exists for given symbol and date"""
        directory = self.base_dir / symbol / date
        directory.mkdir(parents=True, exist_ok=True)
        return directory
        
    def get_latest_part_number(self, directory: Path) -> int:
        """Get the latest part number in the directory"""
        parts = list(directory.glob(f'*_part_*.json'))
        if not parts:
            return 0
        
        part_numbers = [int(p.stem.split('_part_')[1]) for p in parts]
        return max(part_numbers)
        
    def save_message(self, symbol: str, message: str, color: str = 'white'):
        """Save a message to the appropriate JSON file"""
        # Check for duplicate message
        current_message = f"[{symbol}] {message}" if symbol else message
        last_message = self.last_message_content.get(symbol, "")
        
        # If message is duplicate, don't save or print
        if current_message == last_message:
            return
            
        # Update last message
        self.last_message_content[symbol] = current_message
        
        current_time = datetime.now()
        date_str = current_time.strftime("%Y_%m_%d")
        
        # Ensure directory exists
        directory = self.ensure_directory(symbol, date_str)
        
        # Create message data
        message_data = {
            'timestamp': current_time.isoformat(),
            'time': current_time.strftime("%H:%M:%S"),
            'date': current_time.strftime("%Y-%m-%d"),
            'symbol': symbol,
            'message': message,
            'color': color
        }
        
        # Get latest part file
        latest_part = self.get_latest_part_number(directory)
        latest_file = directory / f'{symbol}_part_{latest_part:03d}.json'
        
        # Load existing messages or create new list
        messages = []
        if latest_file.exists():
            with open(latest_file, 'r', encoding='utf-8') as f:
                messages = json.load(f)
                
        # If current file is full, create new part
        if len(messages) >= self.MESSAGES_PER_FILE:
            latest_part += 1
            latest_file = directory / f'{symbol}_part_{latest_part:03d}.json'
            messages = []
            
        # Add new message and save
        messages.append(message_data)
        with open(latest_file, 'w', encoding='utf-8') as f:
            json.dump(messages, f, indent=2, ensure_ascii=False)

# Global instance
logger = MessageLogger()

def message(symbol: str = '', message: str = '', color: str = 'white'):
    """Wrapper function for backwards compatibility"""
    if not symbol:
        # Just print system messages without logging
        current_time = datetime.now().strftime("%H:%M:%S")
        current_date = datetime.now().strftime("%Y-%m-%d")
        print(f"[{current_time}][{current_date}] {message}")
        return
        
    # Create current message for comparison
    current_message = f"[{symbol}] {message}"
    
    # Get last message for this symbol
    last_message = logger.last_message_content.get(symbol, "")
    
    # Only proceed if message is not duplicate
    if current_message != last_message:
        # Log message
        logger.save_message(symbol, message, color)
        
        # Print to console
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
        
        color_prefix = color_code.get(color, '')
        print(f"[{current_time}][{current_date}][{symbol}] {color_prefix}{message}{reset_code}")
        
        # Update last message
        logger.last_message_content[symbol] = current_message
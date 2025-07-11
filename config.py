import os
from pathlib import Path
from dotenv import load_dotenv
from typing import List, Optional
from pydantic import validator
from pydantic_settings import BaseSettings

# Load environment variables from .env file
env_path = Path('.') / '.env'
load_dotenv(dotenv_path=env_path)

class Settings(BaseSettings):
    # Application
    APP_NAME: str = "AIVA Detect System"
    DEBUG: bool = os.getenv('DEBUG', 'False').lower() in ('true', '1', 't')
    
    # Telegram
    BOT_TOKEN: str = os.getenv('BOT_TOKEN', '')
    
    # Parse ADMIN_IDS from environment variable
    ADMIN_IDS: str = '1'  # Store as string to avoid JSON parsing
    
    @property
    def admin_ids_list(self) -> List[int]:
        """Get admin IDs as a list of integers."""
        if not self.ADMIN_IDS.strip():
            return [1]  # Default to admin ID 1 if empty
        if self.ADMIN_IDS.strip().isdigit():
            return [int(self.ADMIN_IDS.strip())]  # Single number
        # Comma-separated list
        return [int(x.strip()) for x in self.ADMIN_IDS.split(',') if x.strip().isdigit()] or [1]
    
    class Config:
        env_file = '.env'
        env_file_encoding = 'utf-8'
        case_sensitive = True
    
    # Database
    DATABASE_DIR: str = os.getenv('DATABASE_DIR', 'instance')
    DATABASE_FILENAME: str = os.getenv('DATABASE_FILENAME', 'aiva_detect.db')
    
    @property
    def DATABASE_URL(self) -> str:
        """Get the database URL, ensuring the directory exists."""
        # Create the database directory if it doesn't exist
        os.makedirs(self.DATABASE_DIR, exist_ok=True)
        # Return the full path to the SQLite database file
        return f"sqlite:///{os.path.join(self.DATABASE_DIR, self.DATABASE_FILENAME)}"
    
    # Logging
    LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FILE: str = 'logs/aiva_bot.log'
    
    class Config:
        case_sensitive = True

# Create settings instance
settings = Settings()

# Create logs directory if it doesn't exist
os.makedirs('logs', exist_ok=True)

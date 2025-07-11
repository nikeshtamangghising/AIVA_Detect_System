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
    ADMIN_IDS: List[int] = [1]  # Default to admin ID 1
    
    @validator('ADMIN_IDS', pre=True)
    def parse_admin_ids(cls, v):
        if isinstance(v, str):
            if not v.strip():
                return [1]  # Default to admin ID 1 if empty
            if v.strip().isdigit():
                return [int(v.strip())]  # Single number
            # Comma-separated list
            return [int(x.strip()) for x in v.split(',') if x.strip().isdigit()]
        return v or [1]  # Default to admin ID 1 if invalid
    
    class Config:
        env_file = '.env'
        env_file_encoding = 'utf-8'
        case_sensitive = True
    
    # Database
    DATABASE_URL: str = os.getenv('DATABASE_URL', 'sqlite:///aiva_detect.db')
    
    # Logging
    LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FILE: str = 'logs/aiva_bot.log'
    
    class Config:
        case_sensitive = True

# Create settings instance
settings = Settings()

# Create logs directory if it doesn't exist
os.makedirs('logs', exist_ok=True)

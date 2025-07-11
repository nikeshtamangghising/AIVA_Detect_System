import os
from pathlib import Path
from dotenv import load_dotenv
from typing import List, Optional
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
    # For testing, accept any number as admin
    ADMIN_IDS: List[int] = [int(x) for x in os.getenv('ADMIN_IDS', '1').split(',') if str(x).strip().isdigit()]
    
    class Config:
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

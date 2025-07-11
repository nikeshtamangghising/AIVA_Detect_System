from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from config import settings
import logging
import os
from urllib.parse import urlparse
from pathlib import Path

# Configure logging
logging.basicConfig(level=settings.LOG_LEVEL)
logger = logging.getLogger(__name__)

def get_database_url():
    """Get the database URL and ensure the directory exists for SQLite."""
    db_url = settings.DATABASE_URL
    
    # Only handle SQLite URLs
    if db_url.startswith('sqlite'):
        # Extract the database path from the URL
        parsed = urlparse(db_url)
        db_path = parsed.path.lstrip('/')
        
        # Create the directory if it doesn't exist
        if db_path != ':memory:':
            db_dir = os.path.dirname(db_path)
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True)
                logger.info(f"Created database directory: {db_dir}")
    
    return db_url

# Get the database URL with directory creation if needed
DATABASE_URL = get_database_url()

# SQLite specific configuration
connect_args = {'check_same_thread': False} if 'sqlite' in DATABASE_URL else {}

# Create database engine with appropriate connection args
engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
    pool_recycle=300,
    echo=settings.LOG_LEVEL == 'DEBUG'  # Enable SQL echo in debug mode
)

# Create a scoped session factory
SessionLocal = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))

# Dependency to get DB session
@contextmanager
def get_db():
    """Database session context manager."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Database error: {e}")
        raise
    finally:
        db.close()

def init_db():
    """Initialize the database."""
    # Import models to register them with SQLAlchemy
    from . import models
    from sqlalchemy.ext.declarative import declarative_base
    
    # Create all tables
    models.Base.metadata.create_all(bind=engine)
    logger.info("Database tables created")

def close_db_connection():
    """Close the database connection."""
    if SessionLocal.registry.has():
        SessionLocal.remove()

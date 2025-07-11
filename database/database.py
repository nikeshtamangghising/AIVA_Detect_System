from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from config import settings
import logging
import os

# Configure logging
logging.basicConfig(level=settings.LOG_LEVEL)
logger = logging.getLogger(__name__)

# SQLite specific configuration
connect_args = {'check_same_thread': False} if 'sqlite' in settings.DATABASE_URL else {}

# Create database engine with appropriate connection args
engine = create_engine(
    settings.DATABASE_URL,
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

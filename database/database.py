from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import declarative_base, scoped_session, sessionmaker
from sqlalchemy import event
from config import settings
import logging
import os

# Ensure the instance folder exists
os.makedirs('instance', exist_ok=True)

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

# Base class for models
Base = declarative_base()
Base.query = SessionLocal.query_property()

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
    import database.models  # Import models to register them with SQLAlchemy
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created")

def close_db_connection():
    """Close the database connection."""
    if SessionLocal.registry.has():
        SessionLocal.remove()

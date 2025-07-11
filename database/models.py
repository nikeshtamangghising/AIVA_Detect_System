from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class PhoneRecord(Base):
    __tablename__ = "phone_records"
    
    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String(20), nullable=False, unique=True, index=True)
    notes = Column(Text, nullable=True)
    group_id = Column(String(100), nullable=True)
    message_id = Column(Integer, nullable=True)
    user_id = Column(Integer, nullable=True)
    is_duplicate = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class DuplicateAlert(Base):
    __tablename__ = "duplicate_alerts"
    
    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String(20), nullable=False)
    original_phone_id = Column(Integer, ForeignKey('phone_records.id'), nullable=False)
    duplicate_phone_id = Column(Integer, ForeignKey('phone_records.id'), nullable=False)
    status = Column(String(20), default="pending")  # pending, resolved
    created_at = Column(DateTime, default=datetime.utcnow)

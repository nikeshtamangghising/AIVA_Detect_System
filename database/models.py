from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from .database import SessionLocal

# Create the declarative base
Base = declarative_base()

# Set up query property for models
Base.query = SessionLocal.query_property()

class IdentifierRecord(Base):
    """Stores unique identifiers that need to be tracked for duplicates.
    
    An identifier can be any unique string such as a phone number, 
    bank account, reference code, etc.
    """
    __tablename__ = "identifier_records"
    
    id = Column(Integer, primary_key=True, index=True)
    identifier = Column(String(100), nullable=False, unique=True, index=True, comment="The unique identifier (phone, account, reference, etc.)")
    identifier_type = Column(String(20), nullable=True, comment="Type of identifier (phone, account, reference, etc.)")
    notes = Column(Text, nullable=True)
    group_id = Column(String(100), nullable=True, comment="ID of the group where this identifier was first seen")
    message_id = Column(Integer, nullable=True, comment="ID of the message where this identifier was first seen")
    user_id = Column(Integer, nullable=True, comment="ID of the user who added this identifier")
    is_duplicate = Column(Boolean, default=False, comment="Whether this is a duplicate of another identifier")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<IdentifierRecord(id={self.id}, identifier='{self.identifier}', type='{self.identifier_type}')>"

class DuplicateAlert(Base):
    """Tracks duplicate identifier detections."""
    __tablename__ = "duplicate_alerts"
    
    id = Column(Integer, primary_key=True, index=True)
    identifier = Column(String(100), nullable=False, comment="The duplicate identifier that was detected")
    original_id = Column(Integer, ForeignKey('identifier_records.id'), nullable=False, comment="Reference to the original identifier record")
    duplicate_id = Column(Integer, ForeignKey('identifier_records.id'), nullable=True, comment="Reference to the duplicate identifier record (if created)")
    status = Column(String(20), default="pending", comment="Status of the alert (pending, resolved)")
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    original = relationship("IdentifierRecord", foreign_keys=[original_id])
    duplicate = relationship("IdentifierRecord", foreign_keys=[duplicate_id])
    
    def __repr__(self):
        return f"<DuplicateAlert(id={self.id}, identifier='{self.identifier}', status='{self.status}')>"

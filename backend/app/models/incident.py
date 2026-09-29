from datetime import datetime, timezone
import uuid
from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.orm import relationship
from ..database import Base

def generate_uuid():
    return str(uuid.uuid4())

class Incident(Base):
    __tablename__ = "incidents"

    id = Column(String(64), primary_key=True, default=generate_uuid, index=True)
    title = Column(String(255), nullable=False)
    service = Column(String(100), nullable=False, index=True)
    severity = Column(String(20), nullable=False, index=True)
    status = Column(String(30), default="open", nullable=False, index=True)
    description = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    evidence_items = relationship("Evidence", back_populates="incident", cascade="all, delete-orphan")
    investigation_jobs = relationship("InvestigationJob", back_populates="incident", cascade="all, delete-orphan")
    reports = relationship("InvestigationReport", back_populates="incident", cascade="all, delete-orphan")

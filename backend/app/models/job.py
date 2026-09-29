from datetime import datetime, timezone
import uuid
from sqlalchemy import Column, String, Integer, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from ..database import Base

def generate_uuid():
    return str(uuid.uuid4())

class InvestigationJob(Base):
    __tablename__ = "investigation_jobs"

    job_id = Column(String(64), primary_key=True, default=generate_uuid, index=True)
    incident_id = Column(String(64), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(30), default="queued", nullable=False, index=True)
    stage = Column(String(100), nullable=True)
    progress = Column(Integer, nullable=True)
    time_window_start = Column(DateTime(timezone=True), nullable=True)
    time_window_end = Column(DateTime(timezone=True), nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    incident = relationship("Incident", back_populates="investigation_jobs")
    reports = relationship("InvestigationReport", back_populates="job", cascade="all, delete-orphan")

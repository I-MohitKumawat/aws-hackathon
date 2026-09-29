from datetime import datetime, timezone
import uuid
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from ..database import Base

def generate_uuid():
    return str(uuid.uuid4())

class InvestigationReport(Base):
    __tablename__ = "investigation_reports"

    id = Column(String(64), primary_key=True, default=generate_uuid, index=True)
    job_id = Column(String(64), ForeignKey("investigation_jobs.job_id", ondelete="CASCADE"), nullable=False, index=True)
    incident_id = Column(String(64), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(30), default="completed", nullable=False)
    summary = Column(Text, nullable=False)
    hypotheses_json = Column(JSON, default=list, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    incident = relationship("Incident", back_populates="reports")
    job = relationship("InvestigationJob", back_populates="reports")

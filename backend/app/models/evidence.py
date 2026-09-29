from datetime import datetime, timezone
import uuid
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from ..database import Base

def generate_uuid():
    return str(uuid.uuid4())

class Evidence(Base):
    __tablename__ = "evidence"

    id = Column(String(64), primary_key=True, default=generate_uuid, index=True)
    incident_id = Column(String(64), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(30), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    service = Column(String(100), nullable=False, index=True)
    severity = Column(String(20), nullable=True)
    message = Column(Text, nullable=False)
    trace_id = Column(String(128), nullable=True, index=True)
    source = Column(String(50), default="otel", nullable=False)
    metadata_json = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    incident = relationship("Incident", back_populates="evidence_items")

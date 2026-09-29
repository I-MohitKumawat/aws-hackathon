from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, ConfigDict
from .common import PaginatedResponse

SeverityType = Literal["low", "medium", "high", "critical"]
IncidentStatus = Literal["open", "investigating", "resolved", "ignored"]

class IncidentBase(BaseModel):
    title: str
    service: str
    severity: SeverityType
    description: Optional[str] = None
    source: Optional[str] = "manual"
    detection_rule: Optional[str] = None
    detection_reason: Optional[str] = None

class IncidentCreate(IncidentBase):
    started_at: datetime

class IncidentUpdate(BaseModel):
    status: Optional[IncidentStatus] = None
    ended_at: Optional[datetime] = None
    title: Optional[str] = None
    description: Optional[str] = None

class IncidentResponse(IncidentBase):
    id: str
    status: IncidentStatus
    started_at: datetime
    ended_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class IncidentListResponse(PaginatedResponse[IncidentResponse]):
    pass

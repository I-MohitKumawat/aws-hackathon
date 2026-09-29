from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field
from .common import PaginatedResponse

EvidenceType = Literal["log", "metric", "trace", "deployment", "event"]

class RawEvidenceItem(BaseModel):
    type: EvidenceType
    timestamp: datetime
    service: str
    message: str
    severity: Optional[str] = None
    trace_id: Optional[str] = None
    source: Optional[str] = "otel"
    metadata: Dict[str, Any] = Field(default_factory=dict)

class TelemetryIngestRequest(BaseModel):
    incident_id: str
    evidence: List[RawEvidenceItem]

class TelemetryIngestResponse(BaseModel):
    incident_id: str
    accepted_count: int
    rejected_count: int

class EvidenceResponse(RawEvidenceItem):
    id: str
    incident_id: str

    model_config = ConfigDict(from_attributes=True)

class EvidenceListResponse(PaginatedResponse[EvidenceResponse]):
    pass

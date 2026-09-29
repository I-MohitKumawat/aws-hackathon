from datetime import datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

HypothesisStatus = Literal["possible", "supported", "inconclusive"]

class Hypothesis(BaseModel):
    id: str
    description: str
    status: HypothesisStatus
    supporting_evidence: List[str] = Field(default_factory=list)
    contradicting_evidence: List[str] = Field(default_factory=list)
    missing_evidence: List[str] = Field(default_factory=list)
    next_step: str

class InvestigationReportResponse(BaseModel):
    id: str
    incident_id: str
    status: str = "completed"
    summary: str
    hypotheses: List[Hypothesis] = Field(default_factory=list)
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

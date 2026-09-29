from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict

JobStatus = Literal["queued", "running", "completed", "failed"]

class TimeWindow(BaseModel):
    start: datetime
    end: datetime

class InvestigationStartRequest(BaseModel):
    time_window: Optional[TimeWindow] = None

class InvestigationJobCreateResponse(BaseModel):
    job_id: str
    incident_id: str
    status: JobStatus
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class InvestigationJobStatusResponse(BaseModel):
    job_id: str
    incident_id: str
    status: JobStatus
    stage: Optional[str] = None
    progress: Optional[int] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    retry_count: int = 0
    max_retries: int = 2
    error: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

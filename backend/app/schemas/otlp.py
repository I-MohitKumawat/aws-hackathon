from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field

class OtlpBaseModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

class KeyValue(OtlpBaseModel):
    key: str
    value: Union[Dict[str, Any], Any] = Field(default_factory=dict)

class Event(OtlpBaseModel):
    timeUnixNano: Optional[Union[str, int]] = None
    name: str = ""
    attributes: Optional[List[KeyValue]] = Field(default_factory=list)

class Status(OtlpBaseModel):
    code: Optional[Union[int, str]] = 0
    message: Optional[str] = ""

class Span(OtlpBaseModel):
    traceId: str
    spanId: str
    parentSpanId: Optional[str] = None
    name: str = ""
    kind: Optional[Union[int, str]] = None
    startTimeUnixNano: Optional[Union[str, int]] = None
    endTimeUnixNano: Optional[Union[str, int]] = None
    attributes: Optional[List[KeyValue]] = Field(default_factory=list)
    events: Optional[List[Event]] = Field(default_factory=list)
    status: Optional[Status] = None

class Scope(OtlpBaseModel):
    name: Optional[str] = None
    version: Optional[str] = None

class ScopeSpan(OtlpBaseModel):
    scope: Optional[Scope] = None
    spans: List[Span] = Field(default_factory=list)

class Resource(OtlpBaseModel):
    attributes: Optional[List[KeyValue]] = Field(default_factory=list)

class ResourceSpan(OtlpBaseModel):
    resource: Optional[Resource] = None
    scopeSpans: List[ScopeSpan] = Field(default_factory=list)

class OtlpTracesPayload(OtlpBaseModel):
    resourceSpans: List[ResourceSpan] = Field(default_factory=list)

class OtlpIngestResponse(BaseModel):
    accepted_spans: int
    rejected_spans: int
    associated_spans: int
    unassociated_spans: int

def parse_otlp_value(val: Any) -> Any:
    """Recursively unpacks OTLP AnyValue JSON object to a native Python value."""
    if not isinstance(val, dict):
        return val
    if "stringValue" in val:
        return val["stringValue"]
    if "intValue" in val:
        try:
            return int(val["intValue"])
        except (ValueError, TypeError):
            return val["intValue"]
    if "doubleValue" in val:
        try:
            return float(val["doubleValue"])
        except (ValueError, TypeError):
            return val["doubleValue"]
    if "boolValue" in val:
        return bool(val["boolValue"])
    if "bytesValue" in val:
        return str(val["bytesValue"])
    if "arrayValue" in val:
        values = val["arrayValue"].get("values", [])
        return [parse_otlp_value(v) for v in values]
    if "kvlistValue" in val:
        values = val["kvlistValue"].get("values", [])
        return {item.get("key"): parse_otlp_value(item.get("value")) for item in values if "key" in item}
    return val

def parse_otlp_attributes(kvs: Optional[List[KeyValue]]) -> Dict[str, Any]:
    """Converts a list of OTLP KeyValue objects to a flattened dictionary."""
    if not kvs:
        return {}
    result = {}
    for kv in kvs:
        result[kv.key] = parse_otlp_value(kv.value)
    return result

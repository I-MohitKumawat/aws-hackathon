from enum import Enum
from typing import Callable, List, Optional
from fastapi import Depends, Request

from ..config import settings
from .exceptions import AppException

class Role(str, Enum):
    ADMIN = "admin"
    INVESTIGATOR = "investigator"
    VIEWER = "viewer"
    TELEMETRY_COLLECTOR = "telemetry_collector"

def extract_api_token(request: Request) -> Optional[str]:
    """
    Extracts authentication token from X-API-Key header or Authorization: Bearer header.
    """
    api_key_header = request.headers.get("X-API-Key") or request.headers.get("x-api-key")
    if api_key_header:
        return api_key_header.strip()

    auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
    if auth_header:
        parts = auth_header.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
        if len(parts) == 1:
            return parts[0].strip()

    return None

def get_current_role(request: Request) -> str:
    """
    Validates token and resolves caller role.
    If AUTH_ENABLED is False, defaults to 'admin' for unrestricted local/testing access.
    """
    if not settings.AUTH_ENABLED:
        return Role.ADMIN.value

    token = extract_api_token(request)
    if not token:
        raise AppException(
            status_code=401,
            code="UNAUTHORIZED",
            message="Authentication credentials were not provided. Provide a valid 'X-API-Key' or 'Authorization: Bearer <token>' header.",
            details={"required_header": "X-API-Key or Authorization: Bearer <token>"},
        )

    role = settings.API_KEYS.get(token)
    if not role:
        raise AppException(
            status_code=401,
            code="INVALID_CREDENTIALS",
            message="The provided authentication token is invalid.",
            details={},
        )

    return role

def require_roles(allowed_roles: List[str]) -> Callable:
    """
    Dependency factory enforcing role-based authorization.
    """
    def dependency(role: str = Depends(get_current_role)) -> str:
        if role not in allowed_roles:
            raise AppException(
                status_code=403,
                code="FORBIDDEN",
                message=f"Access denied. Role '{role}' does not have permission to access this endpoint.",
                details={"role": role, "allowed_roles": allowed_roles},
            )
        return role

    return dependency

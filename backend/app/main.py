from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .database import engine, Base
from .core.exceptions import AppException
from .api.health import router as health_router
from .api.incidents import router as incidents_router
from .api.telemetry import router as telemetry_router
from .api.evidence import router as evidence_router
from .api.investigations import (
    incident_investigations_router,
    investigations_router,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Enable pgvector extension if on PostgreSQL
    try:
        if engine.dialect.name == "postgresql":
            from sqlalchemy import text
            with engine.connect() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                conn.commit()
    except Exception:
        pass
    # Initialize database tables
    Base.metadata.create_all(bind=engine)
    yield

app = FastAPI(
    title="AI Software Incident Investigator API",
    version="1.0.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Standard Error Exception Handlers
@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }
        },
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed.",
                "details": {"errors": exc.errors()},
            }
        },
    )

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": f"An unexpected backend error occurred: {str(exc)}",
                "details": {},
            }
        },
    )

# Register API v1 Routers
app.include_router(health_router, prefix="/api/v1")
app.include_router(incidents_router, prefix="/api/v1")
app.include_router(telemetry_router, prefix="/api/v1")
app.include_router(evidence_router, prefix="/api/v1")
app.include_router(incident_investigations_router, prefix="/api/v1")
app.include_router(investigations_router, prefix="/api/v1")

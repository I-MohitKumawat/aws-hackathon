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
from .api.evidence import router as evidence_router, traces_router
from .api.investigations import (
    incident_investigations_router,
    investigations_router,
)
from .api.otlp import router as otlp_router

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

    # Ensure evidence.incident_id is nullable if existing table had NOT NULL constraint
    try:
        if engine.dialect.name == "sqlite":
            with engine.connect() as conn:
                table_info = conn.exec_driver_sql("PRAGMA table_info(evidence)").fetchall()
                for col in table_info:
                    # col format: (cid, name, type, notnull, dflt_value, pk)
                    if col[1] == "incident_id" and col[3] == 1:
                        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
                        conn.exec_driver_sql("ALTER TABLE evidence RENAME TO _evidence_old")
                        Base.metadata.create_all(bind=engine)
                        conn.exec_driver_sql("INSERT INTO evidence SELECT * FROM _evidence_old")
                        conn.exec_driver_sql("DROP TABLE _evidence_old")
                        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
                        conn.commit()
                        break
        elif engine.dialect.name == "postgresql":
            from sqlalchemy import text
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE evidence ALTER COLUMN incident_id DROP NOT NULL"))
                conn.commit()
    except Exception:
        pass

    # Ensure incidents table has source, detection_rule, and detection_reason columns
    try:
        if engine.dialect.name == "postgresql":
            from sqlalchemy import text
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE incidents ADD COLUMN IF NOT EXISTS source VARCHAR(30) DEFAULT 'manual' NOT NULL"))
                conn.execute(text("ALTER TABLE incidents ADD COLUMN IF NOT EXISTS detection_rule VARCHAR(100)"))
                conn.execute(text("ALTER TABLE incidents ADD COLUMN IF NOT EXISTS detection_reason TEXT"))
                conn.commit()
        elif engine.dialect.name == "sqlite":
            with engine.connect() as conn:
                table_info = conn.exec_driver_sql("PRAGMA table_info(incidents)").fetchall()
                col_names = {col[1] for col in table_info}
                if table_info and "source" not in col_names:
                    conn.exec_driver_sql("ALTER TABLE incidents ADD COLUMN source VARCHAR(30) DEFAULT 'manual' NOT NULL")
                if table_info and "detection_rule" not in col_names:
                    conn.exec_driver_sql("ALTER TABLE incidents ADD COLUMN detection_rule VARCHAR(100)")
                if table_info and "detection_reason" not in col_names:
                    conn.exec_driver_sql("ALTER TABLE incidents ADD COLUMN detection_reason TEXT")
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

# Gzip Request Decompression Middleware (handles compressed OTLP telemetry)
@app.middleware("http")
async def decompress_gzip_requests(request: Request, call_next):
    if request.headers.get("content-encoding") == "gzip":
        body = await request.body()
        try:
            import gzip
            decompressed_body = gzip.decompress(body)
            async def receive():
                return {"type": "http.request", "body": decompressed_body, "more_body": False}
            request = Request(request.scope, receive=receive)
        except Exception:
            pass
    return await call_next(request)

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
app.include_router(traces_router, prefix="/api/v1")
app.include_router(incident_investigations_router, prefix="/api/v1")
app.include_router(investigations_router, prefix="/api/v1")
app.include_router(otlp_router, prefix="/api/v1")
app.include_router(otlp_router)

from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .database import engine, Base, SessionLocal
from .core.exceptions import AppException
from .api.health import router as health_router
from .api.incidents import router as incidents_router
from .api.telemetry import router as telemetry_router
from .api.evidence import router as evidence_router, traces_router, global_evidence_router
from .api.investigations import (
    incident_investigations_router,
    investigations_router,
)
from .api.otlp import router as otlp_router
from .api.admin import router as admin_router
from .services.investigation_service import recover_orphaned_jobs

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Enable pgvector extension if on PostgreSQL
    try:
        if engine.dialect.name == "postgresql":
            from sqlalchemy import text
            with engine.connect() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                conn.commit()
    except Exception:
        pass

    # 2. Ensure evidence.incident_id is nullable if existing table had NOT NULL constraint
    try:
        if engine.dialect.name == "sqlite":
            with engine.connect() as conn:
                table_info = conn.exec_driver_sql("PRAGMA table_info(evidence)").fetchall()
                for col in table_info:
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

    # 3. Ensure incidents table has source, detection_rule, and detection_reason columns
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

    # 4. Ensure investigation_jobs table has retry_count, max_retries, and updated_at columns
    try:
        if engine.dialect.name == "postgresql":
            from sqlalchemy import text
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE investigation_jobs ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0 NOT NULL"))
                conn.execute(text("ALTER TABLE investigation_jobs ADD COLUMN IF NOT EXISTS max_retries INTEGER DEFAULT 2 NOT NULL"))
                conn.execute(text("ALTER TABLE investigation_jobs ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()"))
                conn.commit()
        elif engine.dialect.name == "sqlite":
            with engine.connect() as conn:
                table_info = conn.exec_driver_sql("PRAGMA table_info(investigation_jobs)").fetchall()
                col_names = {col[1] for col in table_info}
                if table_info and "retry_count" not in col_names:
                    conn.exec_driver_sql("ALTER TABLE investigation_jobs ADD COLUMN retry_count INTEGER DEFAULT 0 NOT NULL")
                if table_info and "max_retries" not in col_names:
                    conn.exec_driver_sql("ALTER TABLE investigation_jobs ADD COLUMN max_retries INTEGER DEFAULT 2 NOT NULL")
                if table_info and "updated_at" not in col_names:
                    conn.exec_driver_sql("ALTER TABLE investigation_jobs ADD COLUMN updated_at TIMESTAMP")
                conn.commit()
    except Exception:
        pass

    # 5. Initialize database tables
    Base.metadata.create_all(bind=engine)

    # 6. Step 8: Safe startup recovery of orphaned investigation jobs
    try:
        with SessionLocal() as db:
            rec_stats = recover_orphaned_jobs(db)
            if rec_stats.get("total_orphaned", 0) > 0:
                logger.warning("Startup investigation recovery completed: %s", rec_stats)
    except Exception as exc:
        logger.error("Failed during startup job recovery: %s", exc)

    yield

app = FastAPI(
    title="AI Software Incident Investigator API",
    version="1.0.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# CORS Middleware with restricted allowed methods
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Request Size Limit Middleware (protects backend against oversized ingestion payloads)
@app.middleware("http")
async def limit_request_size(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > settings.MAX_REQUEST_BODY_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={
                        "error": {
                            "code": "PAYLOAD_TOO_LARGE",
                            "message": f"Request body size exceeds maximum limit of {settings.MAX_REQUEST_BODY_BYTES} bytes.",
                            "details": {"max_limit_bytes": settings.MAX_REQUEST_BODY_BYTES},
                        }
                    },
                )
        except ValueError:
            pass
    return await call_next(request)

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
    logger.exception("Unhandled backend error occurred: %s", exc)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected backend error occurred. Sensitive system details have been redacted.",
                "details": {},
            }
        },
    )

# Register API v1 Routers
app.include_router(health_router, prefix="/api/v1")
app.include_router(incidents_router, prefix="/api/v1")
app.include_router(telemetry_router, prefix="/api/v1")
app.include_router(evidence_router, prefix="/api/v1")
app.include_router(global_evidence_router, prefix="/api/v1")
app.include_router(traces_router, prefix="/api/v1")
app.include_router(incident_investigations_router, prefix="/api/v1")
app.include_router(investigations_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(otlp_router, prefix="/api/v1")
app.include_router(otlp_router)

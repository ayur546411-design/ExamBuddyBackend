from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.core.config import settings
from app.core.exceptions import APIException, api_exception_handler, general_exception_handler
import time
import logging
import datetime

logger = logging.getLogger(__name__)
APP_START_TIME = time.time()

def create_app() -> FastAPI:
    # Build the OpenAPI servers list so Swagger UI calls the correct host.
    # When BACKEND_URL is set (production), Swagger will send requests there.
    # When it is empty (local dev), we use relative paths (default behaviour).
    servers = None
    if settings.BACKEND_URL:
        servers = [
            {"url": settings.BACKEND_URL, "description": "Production"},
            {"url": "http://localhost:8000", "description": "Local dev"},
        ]

    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        openapi_url=f"{settings.API_V1_STR}/openapi.json",
        servers=servers,
    )

    # Set all CORS enabled origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Timing + Structured Logging Middleware ──────────────────────────────
    @app.middleware("http")
    async def timing_middleware(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        size = response.headers.get("content-length", "?")
        logger.info(
            f"[API] {request.method} {request.url.path} "
            f"| status={response.status_code} "
            f"| duration={duration_ms}ms "
            f"| size={size}B "
            f"| params={dict(request.query_params)}"
        )
        response.headers["X-Process-Time"] = str(duration_ms)
        return response

    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse
    import logging
    
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        logging.error(f"Validation Error: {exc.errors()} \nBody: {exc.body}")
        return JSONResponse(
            status_code=422,
            content={"detail": exc.errors(), "body": exc.body},
        )
        
    # Exception Handlers
    app.add_exception_handler(APIException, api_exception_handler)
    app.add_exception_handler(Exception, general_exception_handler)

    # Add Routers
    from app.api.v1.endpoints import documents, auth, schools, users, semesters, subjects, ai, notifications, feedback
    app.include_router(auth.router, prefix=settings.API_V1_STR + "/auth", tags=["auth"])
    app.include_router(users.router, prefix=settings.API_V1_STR + "/users", tags=["users"])
    app.include_router(schools.router, prefix=settings.API_V1_STR + "/schools", tags=["schools"])
    app.include_router(semesters.router, prefix=settings.API_V1_STR + "/semesters", tags=["semesters"])
    app.include_router(subjects.router, prefix=settings.API_V1_STR + "/subjects", tags=["subjects"])
    app.include_router(documents.router, prefix=settings.API_V1_STR + "/documents", tags=["documents"])
    app.include_router(notifications.router, prefix=settings.API_V1_STR + "/notifications", tags=["notifications"])
    app.include_router(feedback.router, prefix=settings.API_V1_STR + "/feedback", tags=["feedback"])
    app.include_router(ai.router, prefix=settings.API_V1_STR + "/ai", tags=["ai"])

    @app.get("/")
    async def root():
        return {"message": "Welcome to ExamBuddy API"}

    @app.get("/api/health")
    async def api_health():
        """
        Lightweight health-check endpoint for Render/UptimeRobot monitoring.
        Returns immediately without calling external services (Supabase, Cloudinary, Gemini).
        """
        return {"status": "online"}

    @app.get("/health")
    async def health_check():
        """Lightweight health endpoint — used by mobile app to wake Render and check server status."""
        return {"status": "ok"}

    return app

app = create_app()

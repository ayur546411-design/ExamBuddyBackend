from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.exceptions import APIException, api_exception_handler, general_exception_handler

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        openapi_url=f"{settings.API_V1_STR}/openapi.json"
    )

    # Set all CORS enabled origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"], # In production, restrict this
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from fastapi.exceptions import RequestValidationError
    from fastapi import Request
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
    from app.api.v1.endpoints import documents, auth, schools, users, semesters, subjects, ai
    app.include_router(auth.router, prefix=settings.API_V1_STR + "/auth", tags=["auth"])
    app.include_router(users.router, prefix=settings.API_V1_STR + "/users", tags=["users"])
    app.include_router(schools.router, prefix=settings.API_V1_STR + "/schools", tags=["schools"])
    app.include_router(semesters.router, prefix=settings.API_V1_STR + "/semesters", tags=["semesters"])
    app.include_router(subjects.router, prefix=settings.API_V1_STR + "/subjects", tags=["subjects"])
    app.include_router(documents.router, prefix=settings.API_V1_STR + "/documents", tags=["documents"])
    app.include_router(ai.router, prefix=settings.API_V1_STR + "/ai", tags=["ai"])

    @app.get("/")
    async def root():
        return {"message": "Welcome to ExamBuddy API"}
        
    return app

app = create_app()

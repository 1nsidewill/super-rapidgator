import sys
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse
from loguru import logger

from src.super_rapidgator.core.config import settings
from src.super_rapidgator.api import auth, download, extract, ui
from src.super_rapidgator.core import redis_client


# Configure logging
def setup_logging():
    """Setup application logging with loguru"""
    # Remove default handler
    logger.remove()
    
    # Add console handler with formatting
    logger.add(
        sys.stdout,
        level="DEBUG" if settings.debug else "INFO",
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
               "<level>{level: <8}</level> | "
               "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
               "<level>{message}</level>",
        colorize=True
    )
    
    # Add file handler for production
    if not settings.debug:
        logger.add(
            "logs/app.log",
            rotation="10 MB",
            retention="1 week",
            level="INFO",
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}"
        )


# Lifespan event handler
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan event handler"""
    # Startup
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    logger.info(f"Environment: {'Development' if settings.debug else 'Production'}")
    logger.info(f"Download path: {settings.download_path}")
    
    # Create necessary directories
    Path(settings.download_path).mkdir(parents=True, exist_ok=True)
    Path("logs").mkdir(exist_ok=True)
    
    yield
    
    # Shutdown
    logger.info(f"Shutting down {settings.app_name}")


def create_app() -> FastAPI:
    """Application factory function"""
    # Setup logging first
    setup_logging()
    
    # Create FastAPI app
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Automated Rapidgator download and archive extraction service",
        debug=settings.debug,
        lifespan=lifespan
    )
    
    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.debug else ["http://localhost:8000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Exception handlers
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        logger.error(f"HTTP {exc.status_code}: {exc.detail} - {request.url}")
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.detail,
                "status_code": exc.status_code,
                "path": str(request.url.path)
            }
        )
    
    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled exception: {exc}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "status_code": 500,
                "path": str(request.url.path)
            }
        )
    
    # Middleware for request logging
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start_time = logger.info(f"Request: {request.method} {request.url}")
        
        response = await call_next(request)
        
        process_time = f"{(logger.info.__defaults__ or [0])[0]:.4f}s"
        logger.info(f"Response: {response.status_code} - {process_time}")
        
        return response
    
    # Store templates in app state for access in routers - MOVED
    # app.mount("/static", StaticFiles(directory="static"), name="static")
    # templates = Jinja2Templates(directory="templates")
    # app.state.templates = templates
    
    # Add a development-only endpoint to clear Redis
    if settings.debug:
        @app.get("/dev/clear-redis", tags=["Development"])
        def clear_redis_data():
            """
            Clears all data from the Redis database.
            This is a destructive operation and should only be used in development.
            """
            if redis_client.flush_all_data():
                return {"message": "All data has been successfully flushed from Redis."}
            else:
                raise HTTPException(status_code=500, detail="Failed to flush Redis database.")

    # Include API routers
    app.include_router(ui.router)
    app.include_router(auth.router, prefix="/api")
    app.include_router(download.router, prefix="/api")
    app.include_router(extract.router, prefix="/api")
    
    # Basic routes
    @app.get("/")
    async def root():
        """Root endpoint with service information"""
        return {
            "service": settings.app_name,
            "version": settings.app_version,
            "status": "running",
            "environment": "development" if settings.debug else "production",
            "endpoints": {
                "health": "/health",
                "docs": "/docs",
                "redoc": "/redoc"
            }
        }
    
    @app.get("/health")
    async def health_check():
        """Health check endpoint for monitoring"""
        import os
        
        # Check if download directory is accessible
        download_path_ok = os.path.exists(settings.download_path) and os.access(settings.download_path, os.W_OK)
        
        health_data = {
            "status": "healthy",
            "service": settings.app_name,
            "version": settings.app_version,
            "timestamp": logger.info.__defaults__ if hasattr(logger.info, '__defaults__') else None,
            "checks": {
                "download_path": {
                    "status": "ok" if download_path_ok else "error",
                    "path": settings.download_path,
                    "writable": download_path_ok
                }
            }
        }
        
        status_code = 200 if download_path_ok else 503
        return JSONResponse(content=health_data, status_code=status_code)
    
    logger.info("FastAPI application created successfully")
    return app


# Create the app instance
app = create_app()

# Explicitly mount static files and set up templates for the global app instance
# This is necessary because uvicorn/uv might not run the logic inside create_app
# when discovering the 'app' object.
app.mount("/static", StaticFiles(directory="static"), name="static")
app.state.templates = Jinja2Templates(directory="templates")


if __name__ == "__main__":
    import uvicorn
    
    logger.info(f"Starting {settings.app_name} server...")
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="debug" if settings.debug else "info",
        access_log=True
    )

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse
from typing import List
from loguru import logger
import asyncio
import json

from ..core.config import settings
from ..services.rapidgator_client import rapidgator_client

router = APIRouter(tags=["ui"])

def get_example_response(path: str, method: str) -> str:
    """Generate example API responses for documentation"""
    examples = {
        ("/auth/status", "GET"): {
            "logged_in": True,
            "session_data": {
                "cookies": 7,
                "last_validated": "2024-01-15T10:30:00Z"
            },
            "message": "Session is valid"
        },
        ("/auth/login", "POST"): {
            "success": True,
            "message": "Successfully logged in to Rapidgator",
            "session_data": {
                "cookies": 7,
                "expires_at": "2024-01-16T10:30:00Z"
            }
        },
        ("/auth/logout", "POST"): {
            "success": True,
            "message": "Successfully logged out"
        },
        ("/auth/refresh", "POST"): {
            "success": True,
            "message": "Session refreshed successfully",
            "session_data": {
                "cookies": 7,
                "expires_at": "2024-01-16T10:30:00Z"
            }
        },
        ("/download/start", "POST"): {
            "success": True,
            "message": "Download batch started successfully",
            "batch_id": "batch_20240115_103045_abc123",
            "urls_count": 2,
            "estimated_size": "2.5 GB"
        },
        ("/download/batches", "GET"): {
            "batches": [
                {
                    "id": "batch_20240115_103045_abc123",
                    "name": "My Downloads",
                    "status": "downloading",
                    "created_at": "2024-01-15T10:30:45Z",
                    "urls_count": 2,
                    "completed_count": 1,
                    "failed_count": 0,
                    "total_size": "2.5 GB",
                    "downloaded_size": "1.2 GB"
                }
            ],
            "total_count": 1
        },
        ("/download/batches/{id}", "GET"): {
            "id": "batch_20240115_103045_abc123",
            "name": "My Downloads",
            "status": "downloading",
            "created_at": "2024-01-15T10:30:45Z",
            "completed_at": None,
            "urls": [
                {
                    "url": "https://rapidgator.net/file/example1.zip",
                    "filename": "example1.zip",
                    "status": "completed",
                    "size": "1.2 GB",
                    "downloaded_at": "2024-01-15T10:45:30Z"
                },
                {
                    "url": "https://rapidgator.net/file/example2.rar",
                    "filename": "example2.rar", 
                    "status": "downloading",
                    "size": "1.3 GB",
                    "progress": 0.65
                }
            ],
            "total_size": "2.5 GB",
            "downloaded_size": "1.2 GB"
        },
        ("/download/queue", "GET"): {
            "queue": [
                {
                    "url": "https://rapidgator.net/file/example2.rar",
                    "filename": "example2.rar",
                    "batch_id": "batch_20240115_103045_abc123",
                    "position": 1,
                    "status": "downloading",
                    "progress": 0.65
                }
            ],
            "active_downloads": 1,
            "pending_downloads": 0
        },
        ("/extract/start", "POST"): {
            "success": True,
            "message": "Extraction job started",
            "job_id": "extract_20240115_104500_def456",
            "archive_path": "/downloads/example.zip",
            "extract_path": "/downloads/extracted/example"
        },
        ("/extract/jobs", "GET"): {
            "jobs": [
                {
                    "id": "extract_20240115_104500_def456",
                    "archive_path": "/downloads/example.zip",
                    "extract_path": "/downloads/extracted/example",
                    "status": "completed",
                    "created_at": "2024-01-15T10:45:00Z",
                    "completed_at": "2024-01-15T10:46:30Z",
                    "extracted_files": 15,
                    "total_size": "856 MB"
                }
            ],
            "total_count": 1
        },
        ("/extract/jobs/{id}", "GET"): {
            "id": "extract_20240115_104500_def456",
            "archive_path": "/downloads/example.zip",
            "extract_path": "/downloads/extracted/example",
            "status": "completed",
            "created_at": "2024-01-15T10:45:00Z",
            "completed_at": "2024-01-15T10:46:30Z",
            "extracted_files": [
                "file1.txt",
                "file2.jpg",
                "subfolder/file3.pdf"
            ],
            "total_size": "856 MB",
            "password_required": False
        },
        ("/extract/scan", "POST"): {
            "success": True,
            "message": "Directory scan completed",
            "archives_found": 3,
            "archives": [
                {
                    "path": "/downloads/archive1.zip",
                    "size": "125 MB",
                    "type": "zip"
                },
                {
                    "path": "/downloads/archive2.rar",
                    "size": "890 MB", 
                    "type": "rar"
                },
                {
                    "path": "/downloads/archive3.7z",
                    "size": "450 MB",
                    "type": "7z"
                }
            ]
        }
    }
    
    # Get the example response
    example = examples.get((path, method))
    if example:
        return json.dumps(example, indent=2, ensure_ascii=False)
    
    # Default response
    return json.dumps({
        "success": True,
        "message": "Operation completed successfully"
    }, indent=2, ensure_ascii=False)


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard page"""
    logger.info("Serving main dashboard page")
    
    templates = request.app.state.templates
    
    context = {
        "request": request,
        "title": "Super Rapidgator Dashboard",
        "app_name": settings.app_name,
        "version": settings.app_version,
        "download_path": settings.download_path
    }
    
    return templates.TemplateResponse("dashboard.html", context)


@router.get("/download", response_class=HTMLResponse)
async def download_page(request: Request):
    """Download management page"""
    logger.info("Serving download page")
    
    templates = request.app.state.templates
    
    context = {
        "request": request,
        "title": "Download Manager - Super Rapidgator",
        "page": "download",
        "download_path": settings.download_path
    }
    
    return templates.TemplateResponse("download.html", context)


@router.get("/extract", response_class=HTMLResponse)
async def extract_page(request: Request):
    """Extraction management page"""
    logger.info("Serving extraction page")
    
    templates = request.app.state.templates
    
    context = {
        "request": request,
        "title": "Archive Extraction - Super Rapidgator",
        "page": "extract"
    }
    
    return templates.TemplateResponse("extract.html", context)


@router.get("/auth", response_class=HTMLResponse)
async def auth_page(request: Request):
    """Authentication management page"""
    logger.info("Serving authentication page")
    
    templates = request.app.state.templates
    
    context = {
        "request": request,
        "title": "Authentication - Super Rapidgator",
        "page": "auth"
    }
    
    return templates.TemplateResponse("auth.html", context)


@router.post("/download/submit")
async def submit_download_form(
    request: Request,
    urls: str = Form(...),
    destination: str = Form(None)
):
    """Handle download form submission"""
    logger.info("Processing download form submission")
    
    # Parse URLs from textarea
    url_list = [url.strip() for url in urls.split('\n') if url.strip()]
    
    # TODO: Call download API
    logger.info(f"Received {len(url_list)} URLs for download")
    
    # For now, redirect back to download page
    # In a real implementation, you'd call the download API here
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/download?submitted=true", status_code=303)


@router.get("/api-docs", response_class=HTMLResponse)
async def api_docs_page(request: Request):
    """Custom API documentation page"""
    logger.info("Serving API documentation page")
    
    templates = request.app.state.templates
    
    endpoints = {
        "Authentication": [
            {"method": "GET", "path": "/auth/status", "description": "Check session status"},
            {"method": "POST", "path": "/auth/login", "description": "Login to Rapidgator"},
            {"method": "POST", "path": "/auth/logout", "description": "Logout from Rapidgator"},
            {"method": "POST", "path": "/auth/refresh", "description": "Refresh session"},
        ],
        "Download": [
            {"method": "POST", "path": "/download/start", "description": "Start batch download"},
            {"method": "GET", "path": "/download/batches", "description": "List download batches"},
            {"method": "GET", "path": "/download/batches/{id}", "description": "Get batch details"},
            {"method": "DELETE", "path": "/download/batches/{id}", "description": "Cancel batch"},
            {"method": "GET", "path": "/download/queue", "description": "Get download queue"},
        ],
        "Extraction": [
            {"method": "POST", "path": "/extract/start", "description": "Start extraction job"},
            {"method": "GET", "path": "/extract/jobs", "description": "List extraction jobs"},
            {"method": "GET", "path": "/extract/jobs/{id}", "description": "Get job details"},
            {"method": "DELETE", "path": "/extract/jobs/{id}", "description": "Cancel job"},
            {"method": "POST", "path": "/extract/scan", "description": "Scan directory for archives"},
        ],
    }
    
    context = {
        "request": request,
        "title": "API Documentation - Super Rapidgator",
        "page": "api-docs",
        "endpoints": endpoints,
        "base_url": f"http://{settings.host}:{settings.port}",
        "get_example_response": get_example_response
    }
    
    return templates.TemplateResponse("api_docs.html", context)


@router.get("/status")
async def system_status():
    """System status API for frontend"""
    # This endpoint returns JSON for AJAX calls from the frontend
    
    # Check authentication status
    auth_status = {"authenticated": False, "username": None, "session_expires": None}
    try:
        status_check = await rapidgator_client.get_session_status()
        auth_status = {
            "authenticated": status_check.get("logged_in", False),
            "username": None,  # We don't store username currently
            "session_expires": None
        }
    except Exception as e:
        logger.warning(f"Failed to check auth status for UI: {e}")
    
    # Check download path
    download_path_status = "ok"
    try:
        from pathlib import Path
        download_dir = Path(settings.download_path)
        if not download_dir.exists():
            download_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.error(f"Download path check failed: {e}")
        download_path_status = "error"
    
    # Get active batches count (this would normally come from a download manager)
    active_batches = 0
    try:
        # This is a placeholder - in a real app you'd get this from the download service
        pass
    except Exception:
        pass
    
    return {
        "system": {
            "status": "healthy",
            "uptime": "0d 0h 0m",  # TODO: Calculate actual uptime
            "version": settings.app_version
        },
        "auth": auth_status,
        "download": {
            "active_batches": active_batches,
            "queue_length": 0,
            "download_path_status": download_path_status
        },
        "extraction": {
            "active_jobs": 0,  # TODO: Get from extraction service
            "queue_length": 0
        }
    }


@router.get("/health", include_in_schema=False)
async def ui_health():
    """Health check for UI service"""
    return {
        "service": "Web UI",
        "status": "healthy",
        "templates_configured": True,  # TODO: Check if templates directory exists
        "static_files_configured": True  # TODO: Check if static directory exists
    } 
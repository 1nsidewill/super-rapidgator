from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Dict, Any
from enum import Enum
from pathlib import Path
from loguru import logger

from ..core.config import settings

router = APIRouter(prefix="/extract", tags=["extraction"])


class ExtractionStatus(str, Enum):
    """Extraction status enumeration"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExtractionRequest(BaseModel):
    """Archive extraction request model"""
    source_path: str
    destination_path: str | None = None
    recursive: bool = True
    cleanup_archives: bool = True
    max_depth: int | None = None


class ExtractionItem(BaseModel):
    """Individual extraction item model"""
    id: str
    source_file: str
    destination: str
    archive_type: str
    status: ExtractionStatus
    progress: float = 0.0
    error_message: str | None = None
    extracted_files: List[str] = []
    nested_archives: List[str] = []


class ExtractionJob(BaseModel):
    """Extraction job information model"""
    job_id: str
    source_path: str
    destination_path: str
    total_archives: int
    completed_archives: int
    failed_archives: int
    status: ExtractionStatus
    recursive: bool
    cleanup_archives: bool
    max_depth: int
    created_at: str
    items: List[ExtractionItem]


# In-memory storage for demo (TODO: Replace with proper database)
extraction_jobs: Dict[str, ExtractionJob] = {}


def mock_extraction_task(job_id: str, source_path: str, config: dict):
    """Mock background extraction task"""
    logger.info(f"Starting extraction job {job_id} for path: {source_path}")
    # TODO: Implement actual extraction logic


@router.post("/start", response_model=ExtractionJob)
async def start_extraction(
    extraction_request: ExtractionRequest,
    background_tasks: BackgroundTasks
):
    """Start archive extraction and cleanup process"""
    logger.info(f"Starting extraction for: {extraction_request.source_path}")
    
    # Validate source path exists
    source_path = Path(extraction_request.source_path)
    if not source_path.exists():
        raise HTTPException(status_code=404, detail="Source path not found")
    
    # Set destination path
    destination = extraction_request.destination_path or str(source_path)
    
    # Create job ID
    import uuid
    job_id = str(uuid.uuid4())
    
    # Find archive files
    archive_extensions = {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"}
    archive_files = []
    
    if source_path.is_file() and source_path.suffix.lower() in archive_extensions:
        archive_files = [str(source_path)]
    elif source_path.is_dir():
        for ext in archive_extensions:
            archive_files.extend([str(p) for p in source_path.rglob(f"*{ext}")])
    
    # Create extraction items
    items = []
    for i, archive_file in enumerate(archive_files):
        archive_path = Path(archive_file)
        item = ExtractionItem(
            id=f"{job_id}-{i}",
            source_file=archive_file,
            destination=destination,
            archive_type=archive_path.suffix.lower()[1:],  # Remove dot
            status=ExtractionStatus.PENDING
        )
        items.append(item)
    
    # Create extraction job
    job = ExtractionJob(
        job_id=job_id,
        source_path=str(source_path),
        destination_path=destination,
        total_archives=len(items),
        completed_archives=0,
        failed_archives=0,
        status=ExtractionStatus.PENDING,
        recursive=extraction_request.recursive,
        cleanup_archives=extraction_request.cleanup_archives,
        max_depth=extraction_request.max_depth or settings.max_extraction_depth,
        created_at="2024-01-01T12:00:00Z",  # TODO: Use actual timestamp
        items=items
    )
    
    # Store job
    extraction_jobs[job_id] = job
    
    # Start background extraction task
    config = {
        "recursive": extraction_request.recursive,
        "cleanup": extraction_request.cleanup_archives,
        "max_depth": job.max_depth
    }
    background_tasks.add_task(mock_extraction_task, job_id, str(source_path), config)
    
    logger.info(f"Created extraction job {job_id} with {len(items)} archives")
    return job


@router.get("/jobs", response_model=List[ExtractionJob])
async def list_extraction_jobs():
    """List all extraction jobs"""
    logger.info("Listing all extraction jobs")
    return list(extraction_jobs.values())


@router.get("/jobs/{job_id}", response_model=ExtractionJob)
async def get_extraction_job(job_id: str):
    """Get specific extraction job details"""
    logger.info(f"Getting extraction job {job_id}")
    
    if job_id not in extraction_jobs:
        raise HTTPException(status_code=404, detail="Extraction job not found")
    
    return extraction_jobs[job_id]


@router.delete("/jobs/{job_id}")
async def cancel_extraction_job(job_id: str):
    """Cancel an extraction job"""
    logger.info(f"Cancelling extraction job {job_id}")
    
    if job_id not in extraction_jobs:
        raise HTTPException(status_code=404, detail="Extraction job not found")
    
    # TODO: Implement actual cancellation logic
    job = extraction_jobs[job_id]
    job.status = ExtractionStatus.CANCELLED
    
    return {"message": f"Extraction job {job_id} cancelled"}


@router.post("/scan")
async def scan_directory(path: str):
    """Scan directory for archive files"""
    logger.info(f"Scanning directory: {path}")
    
    scan_path = Path(path)
    if not scan_path.exists():
        raise HTTPException(status_code=404, detail="Directory not found")
    
    if not scan_path.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")
    
    # Find archive files
    archive_extensions = {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"}
    archives = []
    
    for ext in archive_extensions:
        for archive_file in scan_path.rglob(f"*{ext}"):
            archives.append({
                "path": str(archive_file),
                "name": archive_file.name,
                "size": archive_file.stat().st_size,
                "type": ext[1:],  # Remove dot
                "parent_dir": str(archive_file.parent)
            })
    
    return {
        "scan_path": path,
        "total_archives": len(archives),
        "archives": archives,
        "supported_formats": list(archive_extensions)
    }


@router.get("/queue")
async def get_extraction_queue():
    """Get current extraction queue status"""
    active_jobs = [
        job for job in extraction_jobs.values()
        if job.status in [ExtractionStatus.PENDING, ExtractionStatus.IN_PROGRESS]
    ]
    
    return {
        "active_jobs": len(active_jobs),
        "queue": [
            {
                "job_id": job.job_id,
                "source_path": job.source_path,
                "total_archives": job.total_archives,
                "status": job.status
            }
            for job in active_jobs
        ]
    }


@router.get("/health")
async def extraction_health():
    """Health check for extraction service"""
    import shutil
    
    # Check if extraction tools are available
    tools_available = {
        "unzip": shutil.which("unzip") is not None,
        "7z": shutil.which("7z") is not None,
        "tar": shutil.which("tar") is not None,
    }
    
    return {
        "service": "Archive Extraction",
        "status": "healthy",
        "config": {
            "extract_nested": settings.extract_nested,
            "cleanup_archives": settings.cleanup_archives,
            "max_depth": settings.max_extraction_depth
        },
        "tools": tools_available,
        "stats": {
            "total_jobs": len(extraction_jobs),
            "active_jobs": len([
                j for j in extraction_jobs.values()
                if j.status in [ExtractionStatus.PENDING, ExtractionStatus.IN_PROGRESS]
            ])
        }
    } 
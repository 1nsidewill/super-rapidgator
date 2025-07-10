import time
from typing import List, Optional

from pydantic import BaseModel, Field


class DownloadItem(BaseModel):
    id: str
    url: str
    filename: str
    status: str = "pending"
    progress: float = 0.0
    total_size_bytes: int = 0
    downloaded_bytes: int = 0
    error_message: Optional[str] = None
    task_id: Optional[str] = None


class DownloadBatch(BaseModel):
    id: str
    name: str
    items: List[DownloadItem]
    status: str = "pending"
    created_at: float = Field(default_factory=time.time)
    total_items: int = 0
    completed_items: int = 0
    # These will be calculated fields
    total_size_bytes: int = 0
    downloaded_bytes: int = 0
    progress: float = 0.0
    progress_percentage: float = 0.0
    use_celery: bool = False
    celery_task_id: Optional[str] = None

    def update_progress(self):
        """Manually update progress fields based on items."""
        if not self.items:
            return

        self.total_items = len(self.items)
        self.completed_items = sum(1 for item in self.items if item.status == "completed")
        self.total_size_bytes = sum(item.total_size_bytes for item in self.items if item.total_size_bytes)
        self.downloaded_bytes = sum(item.downloaded_bytes for item in self.items if item.downloaded_bytes)

        if self.total_size_bytes > 0:
            self.progress = self.downloaded_bytes / self.total_size_bytes
        else:
            self.progress = 0.0
        
        self.progress_percentage = self.progress * 100 
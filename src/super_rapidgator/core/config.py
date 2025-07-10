import os
import platform
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings"""
    
    # App settings
    app_name: str = "Super Rapidgator"
    app_version: str = "0.1.0"
    debug: bool = False
    
    # Server settings
    host: str = "0.0.0.0"
    port: int = 8000
    
    # Browser settings
    browser_headless: bool = True
    browser_timeout: int = 30000  # 30 seconds
    
    # Rapidgator settings
    rapidgator_login_url: str = "https://rapidgator.net/auth/login"
    rapidgator_username: Optional[str] = None
    rapidgator_password: Optional[str] = None
    rapidgator_session_timeout: int = 3600  # 1 hour
    
    # Download settings - 환경에 따라 다른 기본값
    download_path: str = ""  # 기본값은 빈 문자열로 설정
    max_download_size: int = 10 * 1024 * 1024 * 1024  # 10GB
    max_concurrent_downloads: int = 5
    
    # Redis settings
    redis_host: str = ""  # 기본값 비워두기
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: Optional[str] = None
    redis_url: Optional[str] = None
    
    # Celery
    CELERY_BROKER_URL: str = "redis://10.0.0.1:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://10.0.0.1:6379/0"
    CELERY_TASK_SERIALIZER: str = "json"
    CELERY_ACCEPT_CONTENT: list[str] = ["json"]
    CELERY_RESULT_SERIALIZER: str = "json"
    CELERY_TIMEZONE: str = "UTC"
    CELERY_ENABLE_UTC: bool = True
    CELERY_TASK_TRACK_STARTED: bool = True
    CELERY_TASK_TIME_LIMIT: int = 3600
    CELERY_TASK_SOFT_TIME_LIMIT: int = 3300
    CELERY_WORKER_CONCURRENCY: int = 4
    CELERY_ENABLED: bool = True
    
    # Archive settings
    archive_extract_path: str = ""  # 기본값은 빈 문자열로 설정
    archive_password: Optional[str] = None
    archive_supported_formats: list = ["zip", "rar", "7z", "tar", "gz"]
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        # OS별 기본 경로 설정
        if not self.download_path:
            if platform.system() == "Darwin":  # macOS
                self.download_path = "./downloads"
            else:  # Linux/Windows
                self.download_path = "/downloads" if self.debug else "./downloads"
        
        if not self.archive_extract_path:
            if platform.system() == "Darwin":  # macOS
                self.archive_extract_path = "./extracted"
            else:  # Linux/Windows
                self.archive_extract_path = "/extracted" if self.debug else "./extracted"
        
        # 경로 생성
        Path(self.download_path).mkdir(parents=True, exist_ok=True)
        Path(self.archive_extract_path).mkdir(parents=True, exist_ok=True)
        
        # Redis 호스트 분기 처리
        if not self.redis_host:
            if self.debug:
                self.redis_host = "10.0.0.1"   # 디버그(개발) 모드
            else:
                self.redis_host = "redis"      # 배포(도커/서버) 모드
        if not self.redis_url:
            if self.redis_password:
                self.redis_url = f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
            else:
                self.redis_url = f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"
        
        # Celery URL 자동 생성
        if not self.CELERY_BROKER_URL:
            self.CELERY_BROKER_URL = self.redis_url
        
        if not self.CELERY_RESULT_BACKEND:
            self.CELERY_RESULT_BACKEND = self.redis_url
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# 전역 설정 인스턴스
settings = Settings() 
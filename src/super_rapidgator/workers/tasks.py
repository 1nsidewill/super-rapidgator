"""Celery 백그라운드 태스크들"""

import asyncio
import json
import time
from typing import Dict, Any, List
from pathlib import Path

from celery import current_task
from celery.exceptions import Retry
from loguru import logger

# Redis helpers
from ..core.redis_client import (
    redis_client,
    save_batch,
    publish_event,
    get_batch_key,
    update_batch_status,
)
import json

from .celery_app import celery_app
from ..core.config import settings
from ..services.rapidgator_client import RapidgatorClient
from ..models.download import DownloadBatch
from .celery_app import celery_app, LogErrorsTask

# redis WatchError
import redis


@celery_app.task(bind=True, base=LogErrorsTask)
def download_file_task(self, url: str, batch_id: str, item_id: str, download_dir: str = None) -> Dict[str, Any]:
    """
    개별 파일 다운로드 태스크
    각 URL을 개별 Celery job으로 처리
    """
    task_id = self.request.id
    logger.info(f"다운로드 태스크 시작: {task_id} - URL: {url}")
    
    # 다운로드 디렉토리 설정
    if not download_dir:
        download_dir = settings.download_path
    
    # 태스크 시작 상태 업데이트
    self.update_state(
        state="PROGRESS",
        meta={
            "current": 0,
            "total": 100,
            "status": "다운로드 준비 중...",
            "url": url,
            "batch_id": batch_id,
            "item_id": item_id,
            "filename": None,
            "file_size": 0,
            "download_speed": 0,
            "eta": None,
            "started_at": time.time()
        }
    )
    
    try:
        # 비동기 다운로드를 동기적으로 실행
        result = asyncio.run(_download_file_async(self, url, batch_id, item_id, download_dir))
        
        logger.info(f"다운로드 완료: {task_id} - {result.get('filename', 'Unknown')}")

        # Redis 상태 갱신 & 이벤트 발행
        _patch_item(batch_id, item_id, {
            "status": "completed" if result.get("success") else "failed",
            "filename": result.get("filename"),
            "file_size": result.get("file_size"),
        })

        publish_event(f"batch:{batch_id}:events", {
            "type": "item_completed",
            "item_id": item_id,
            "success": result.get("success", False),
        })
        
        return result
        
    except Exception as e:
        logger.error(f"다운로드 실패: {task_id} - {str(e)}")
        
        # 재시도 로직
        if self.request.retries < self.max_retries:
            logger.info(f"재시도 {self.request.retries + 1}/{self.max_retries}: {task_id}")
            
            self.update_state(
                state="RETRY",
                meta={
                    "current": 0,
                    "total": 100,
                    "status": f"재시도 중... ({self.request.retries + 1}/{self.max_retries})",
                    "url": url,
                    "batch_id": batch_id,
                    "item_id": item_id,
                    "error": str(e),
                    "retry_count": self.request.retries + 1,
                    "max_retries": self.max_retries
                }
            )
            
            # 지수적 백오프로 재시도
            countdown = 2 ** self.request.retries
            raise self.retry(countdown=countdown, exc=e)
        
        # 최종 실패
        _patch_item(batch_id, item_id, {
            "status": "failed",
            "error_message": str(e),
        })

        publish_event(f"batch:{batch_id}:events", {
            "type": "item_failed",
            "item_id": item_id,
            "error": str(e),
        })

        return {
            "success": False,
            "error": str(e),
            "url": url,
            "batch_id": batch_id,
            "item_id": item_id,
            "task_id": task_id,
            "retries": self.request.retries,
            "failed_at": time.time()
        }


async def _download_file_async(task, url: str, batch_id: str, item_id: str, download_dir: str) -> Dict[str, Any]:
    """비동기 다운로드 실행 (파일 존재 시 선스킵)"""
    import os, aiohttp
    """비동기 다운로드 실행"""
    client = None
    # 선행 스킵 검사 ----------------------------------------------------------
    try:
        filename_candidate = os.path.basename(url.split('/')[-1])
        if filename_candidate.endswith('.html'):
            filename_candidate = filename_candidate[:-5]
        local_path = os.path.join(download_dir, filename_candidate)
        if os.path.exists(local_path):
            existing_size = os.path.getsize(local_path)
            remote_size = None
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.head(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        if resp.status == 200:
                            remote_size = int(resp.headers.get('Content-Length', '0') or 0)
            except Exception:
                pass

            if remote_size is None or remote_size == 0 or remote_size == existing_size:
                logger.info(f"이미 존재하고 크기 동일 → 스킵: {filename_candidate}")
                _patch_item(batch_id, item_id, {
                    "status": "completed",
                    "filename": filename_candidate,
                    "file_size": existing_size,
                    "progress": 100.0,
                })
                publish_event(f"batch:{batch_id}:events", {
                    "type": "item_skipped",
                    "item_id": item_id,
                })
                return {
                    "success": True,
                    "skipped": True,
                    "filename": filename_candidate,
                    "file_size": existing_size,
                    "url": url,
                    "batch_id": batch_id,
                    "item_id": item_id,
                    "task_id": task.request.id,
                }
    except Exception as precheck_err:
        logger.debug("skip 검사 오류: {}", precheck_err)
    # ----------------------------------------------------------------------
    
    try:
        # 진행 상태 업데이트
        task.update_state(
            state="PROGRESS",
            meta={
                "current": 10,
                "total": 100,
                "status": "클라이언트 초기화 중...",
                "url": url,
                "batch_id": batch_id,
                "item_id": item_id
            }
        )
        
        # RapidgatorClient 초기화
        client = RapidgatorClient()
        
        # 로그인 확인
        task.update_state(
            state="PROGRESS",
            meta={
                "current": 20,
                "total": 100,
                "status": "로그인 확인 중...",
                "url": url,
                "batch_id": batch_id,
                "item_id": item_id
            }
        )
        
        logged_in = await client.ensure_logged_in()
        if not logged_in:
            return {
                "success": False,
                "error": "Rapidgator 로그인 실패",
                "url": url,
                "batch_id": batch_id,
                "item_id": item_id,
                "task_id": task.request.id
            }
        
        # 다운로드 시작
        task.update_state(
            state="PROGRESS",
            meta={
                "current": 30,
                "total": 100,
                "status": "다운로드 시작...",
                "url": url,
                "batch_id": batch_id,
                "item_id": item_id
            }
        )
        
        # 실제 다운로드 수행
        download_result = await client.download_file(url, download_dir)
        
        if download_result.get("success", False):
            # 성공 시 진행률 100%로 업데이트
            task.update_state(
                state="PROGRESS",
                meta={
                    "current": 100,
                    "total": 100,
                    "status": "다운로드 완료!",
                    "url": url,
                    "batch_id": batch_id,
                    "item_id": item_id,
                    "filename": download_result.get("filename"),
                    "file_size": download_result.get("file_size", 0),
                    "completed_at": time.time()
                }
            )
            
            return {
                "success": True,
                "filename": download_result.get("filename"),
                "file_path": download_result.get("file_path"),
                "file_size": download_result.get("file_size", 0),
                "url": url,
                "batch_id": batch_id,
                "item_id": item_id,
                "task_id": task.request.id,
                "download_url": download_result.get("download_url"),
                "completed_at": time.time()
            }
        else:
            return {
                "success": False,
                "error": download_result.get("error", "다운로드 실패"),
                "url": url,
                "batch_id": batch_id,
                "item_id": item_id,
                "task_id": task.request.id
            }
            
    except Exception as e:
        logger.error(f"비동기 다운로드 오류: {str(e)}")
        raise e
    
    finally:
        # 클라이언트 정리
        if client:
            try:
                await client.close()
            except Exception as cleanup_error:
                logger.warning(f"클라이언트 정리 오류: {cleanup_error}")


@celery_app.task(bind=True, name="batch_download")
def batch_download_task(self, batch_data: dict):
    """
    Receives a batch of download items and creates individual download tasks for each.
    """
    batch = DownloadBatch(**batch_data)
    logger.info(f"배치 다운로드 시작: {batch.id} ({batch.total_items}개 파일)")

    # Fix: Use the imported function directly, not as a method of redis_client
    update_batch_status(batch.id, "active")

    for item in batch.items:
        # Dispatch a download task for each item
        logger.info(f"파일 다운로드 태스크 생성: {item.id} - {item.url}")
        # Use keyword arguments for clarity and to avoid errors
        download_file_task.delay(
            url=str(item.url), 
            batch_id=batch.id, 
            item_id=item.id
        )

    return {"status": "Batch processing started", "batch_id": batch.id}


@celery_app.task(bind=True, name="cleanup_completed_tasks")
def cleanup_completed_tasks(self, max_age_hours: int = 24) -> Dict[str, Any]:
    """
    완료된 태스크 정리 (선택사항)
    """
    task_id = self.request.id
    logger.info(f"태스크 정리 시작: {task_id} - {max_age_hours}시간 이전 태스크들")
    
    try:
        # 여기서는 간단히 로그만 남기고, 실제 정리는 Redis/Celery 설정으로 처리
        logger.info("태스크 정리 완료")
        
        return {
            "success": True,
            "task_id": task_id,
            "cleaned_at": time.time(),
            "max_age_hours": max_age_hours
        }
        
    except Exception as e:
        logger.error(f"태스크 정리 실패: {task_id} - {str(e)}")
        
        return {
            "success": False,
            "error": str(e),
            "task_id": task_id,
            "failed_at": time.time()
        }


# 태스크 상태 헬퍼 함수들
def get_task_status(task_id: str) -> Dict[str, Any]:
    """특정 태스크의 상태를 조회"""
    try:
        result = celery_app.AsyncResult(task_id)
        
        return {
            "task_id": task_id,
            "status": result.status,
            "result": result.result,
            "info": result.info,
            "successful": result.successful(),
            "failed": result.failed(),
            "ready": result.ready(),
            "date_done": result.date_done.isoformat() if result.date_done else None
        }
    except Exception as e:
        logger.error(f"태스크 상태 조회 실패: {task_id} - {str(e)}")
        return {
            "task_id": task_id,
            "status": "ERROR",
            "error": str(e)
        }


def get_batch_status(batch_id: str, download_tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """배치 다운로드의 전체 상태를 조회"""
    try:
        completed = 0
        failed = 0
        in_progress = 0
        pending = 0
        
        task_statuses = []
        
        for task_info in download_tasks:
            task_id = task_info["task_id"]
            status = get_task_status(task_id)
            
            task_statuses.append({
                **task_info,
                "status": status["status"],
                "result": status.get("result"),
                "successful": status.get("successful", False),
                "failed": status.get("failed", False),
                "ready": status.get("ready", False)
            })
            
            if status["status"] == "SUCCESS":
                completed += 1
            elif status["status"] == "FAILURE":
                failed += 1
            elif status["status"] in ["PROGRESS", "RETRY"]:
                in_progress += 1
            else:
                pending += 1
        
        total = len(download_tasks)
        
        # 전체 상태 결정
        if completed == total:
            overall_status = "COMPLETED"
        elif failed == total:
            overall_status = "FAILED"
        elif completed + failed == total:
            overall_status = "COMPLETED_WITH_ERRORS"
        elif in_progress > 0:
            overall_status = "IN_PROGRESS"
        else:
            overall_status = "PENDING"
        
        return {
            "batch_id": batch_id,
            "overall_status": overall_status,
            "total_tasks": total,
            "completed": completed,
            "failed": failed,
            "in_progress": in_progress,
            "pending": pending,
            "progress_percentage": (completed / total * 100) if total > 0 else 0,
            "task_statuses": task_statuses
        }
        
    except Exception as e:
        logger.error(f"배치 상태 조회 실패: {batch_id} - {str(e)}")
        return {
            "batch_id": batch_id,
            "overall_status": "ERROR",
            "error": str(e)
        } 

# --------------------------------------------------------------------------------------
# Redis Patch Helper -------------------------------------------------------------------
# --------------------------------------------------------------------------------------


def _patch_item(batch_id: str, item_id: str, patch: Dict[str, Any]) -> None:
    """Atomically update a single item's fields inside the batch JSON in Redis."""
    key = get_batch_key(batch_id)
    pipe = redis_client.pipeline()
    while True:
        try:
            pipe.watch(key)
            raw = pipe.get(key)
            if raw is None:
                pipe.unwatch()
                return
            data = json.loads(raw)
            for item in data.get("items", []):
                if item.get("item_id") == item_id or item.get("id") == item_id:
                    item.update(patch)
                    break
            
            # Recompute aggregate stats and batch status
            total_items = len(data.get("items", []))
            completed_items = sum(1 for it in data["items"] if it.get("status") == "completed")
            failed_items = sum(1 for it in data["items"] if it.get("status") == "failed")

            data["completed_items"] = completed_items
            data["failed_items"] = failed_items
            data["total_items"] = total_items

            # Determine overall batch status
            if completed_items == total_items and total_items > 0:
                data["status"] = "completed"
                data["completed_at"] = time.time()
            elif failed_items == total_items and total_items > 0:
                data["status"] = "failed"
                data["completed_at"] = time.time()
            elif completed_items + failed_items == total_items and total_items > 0:
                data["status"] = "completed_with_errors"
                data["completed_at"] = time.time()
            else:
                # still processing
                data["status"] = "downloading"
                data.pop("completed_at", None)

            pipe.multi()
            pipe.set(key, json.dumps(data))
            pipe.execute()

            # Broadcast updated snapshot to global channel for UI lists
            try:
                publish_event("batch:all:events", {"type": "snapshot", "data": data})
            except Exception as exc:
                logger.debug("broadcast failure: {}", exc)
            break
        except redis.exceptions.WatchError:  # type: ignore
            continue
        finally:
            pipe.reset() 
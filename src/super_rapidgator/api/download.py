"""다운로드 API 엔드포인트"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, HttpUrl
from typing import List, Optional, Dict, Any
import json
import time
import uuid
from loguru import logger

# Celery / workers
from ..workers.tasks import batch_download_task, get_task_status, get_batch_status
from ..workers.celery_app import celery_app

# Redis/core helpers
from ..core.redis_client import (
    save_batch,
    get_batch as redis_get_batch,
    redis_client,
    publish_event,
    get_batch_key,
)
from ..core.config import settings

# For async Redis Pub/Sub
import redis.asyncio as aioredis

# DownloadItem and DownloadBatch models are now in models/download.py
from ..models.download import DownloadItem, DownloadBatch

router = APIRouter(prefix="/download", tags=["Download"])


class DownloadRequest(BaseModel):
    urls: List[HttpUrl]
    batch_name: Optional[str] = None
    use_celery: bool = True  # Celery 사용 여부


# DownloadItem and DownloadBatch models are now in models/download.py

# ----------------------------------------------------------------------------
# NOTE: 기존 in-memory dict → Redis 전환
# ----------------------------------------------------------------------------
# download_batches: Dict[str, DownloadBatch] = {}

# Helper to list all batches from Redis

def list_all_batches(status_filter: Optional[str] = None) -> List[Dict[str, Any]]:  # 타입 수정
    """
    Redis에서 모든 배치를 조회합니다.
    status_filter를 사용하여 'active', 'pending' 등의 상태로 필터링할 수 있습니다.
    """
    logger.info(f"🔍 list_all_batches 호출됨: status_filter={status_filter}")
    
    batches: List[Dict[str, Any]] = []
    batch_count = 0
    
    # Redis 키 확인
    redis_keys = list(redis_client.scan_iter("batch:*"))
    logger.info(f"📦 Redis에서 발견된 배치 키: {len(redis_keys)}개 - {redis_keys}")
    
    for key in redis_keys:
        batch_count += 1
        logger.debug(f"🔄 배치 키 처리 중 ({batch_count}/{len(redis_keys)}): {key}")
        
        raw = redis_client.get(key)
        if not raw:
            logger.warning(f"❌ 빈 배치 데이터: {key}")
            continue
            
        try:
            data: Dict[str, Any] = json.loads(raw)
            batch_id = data.get('id', 'unknown')
            batch_status = data.get('status', 'unknown')
            
            logger.debug(f"📋 배치 데이터 파싱 성공: {batch_id} - status: {batch_status}")

            # 데이터 클렌징: items 내부의 None 값을 0으로 변환
            items = data.get("items", [])
            logger.debug(f"📁 배치 {batch_id}의 아이템 개수: {len(items)}")
            
            for item_data in items:
                if item_data.get("total_size_bytes") is None:
                    item_data["total_size_bytes"] = 0
                if item_data.get("downloaded_bytes") is None:
                    item_data["downloaded_bytes"] = 0

            # --- reconcile aggregate counts for legacy or partially updated batches ---
            total_items = len(items)
            completed_items = sum(1 for it in items if it.get("status") == "completed")
            failed_items = sum(1 for it in items if it.get("status") == "failed")
            
            data["total_items"] = total_items
            data["completed_items"] = completed_items
            data["failed_items"] = failed_items
            
            logger.debug(f"📊 배치 {batch_id} 통계: 전체={total_items}, 완료={completed_items}, 실패={failed_items}")
            
            # 상태 업데이트 로직
            original_status = data.get("status")
            if total_items > 0:
                if completed_items == total_items:
                    data["status"] = "completed"
                    data.setdefault("completed_at", time.time())
                elif failed_items == total_items:
                    data["status"] = "failed"
                    data.setdefault("completed_at", time.time())
                elif completed_items + failed_items == total_items:
                    data["status"] = "completed_with_errors"
                    data.setdefault("completed_at", time.time())
                elif any(it.get("status") == "downloading" for it in items):
                     data["status"] = "downloading"
            
            if original_status != data["status"]:
                logger.info(f"🔄 배치 {batch_id} 상태 변경: {original_status} → {data['status']}")
            
            # 상태 필터 적용
            if status_filter:
                # 'active'는 'downloading'과 'pending'을 모두 포함하도록 처리
                allowed_statuses = [s.strip() for s in status_filter.split(',')]
                if "active" in allowed_statuses:
                    allowed_statuses.extend(["downloading", "pending"])
                
                logger.debug(f"🎯 필터링 체크: 허용된상태={allowed_statuses}, 배치상태={data.get('status')}")
                
                if data.get("status") not in allowed_statuses:
                    logger.debug(f"🚫 배치 {batch_id} 필터링됨 (상태: {data.get('status')})")
                    continue
                else:
                    logger.debug(f"✅ 배치 {batch_id} 필터 통과")

            batches.append(data)
            logger.debug(f"➕ 배치 {batch_id} 결과에 추가됨")

        except json.JSONDecodeError as e:
            logger.error(f"💥 배치 JSON 파싱 실패 {key}: {e}")
            continue
        except Exception as exc:
            logger.error(f"💥 배치 처리 중 예외 발생 {key}: {exc}", exc_info=True)
            continue
    
    # 결과 정렬
    sorted_batches = sorted(batches, key=lambda b: b.get("created_at", 0), reverse=True)
    
    logger.info(f"🎉 배치 조회 완료: 전체 {batch_count}개 중 {len(sorted_batches)}개 반환")
    
    # 반환되는 배치들의 요약 로그
    if sorted_batches:
        logger.info("📋 반환되는 배치 목록:")
        for batch in sorted_batches:
            batch_id = batch.get('id', 'unknown')
            batch_status = batch.get('status', 'unknown') 
            total_items = batch.get('total_items', 0)
            completed_items = batch.get('completed_items', 0)
            logger.info(f"  - {batch_id}: {batch_status} ({completed_items}/{total_items})")
    else:
        logger.warning("⚠️ 반환할 배치가 없습니다")
    
    return sorted_batches


@router.post("/start", status_code=201)
async def start_download(
    download_request: DownloadRequest, background_tasks: BackgroundTasks
):
    urls = [str(url) for url in download_request.urls]
    # 추가: URL 유효성 검사 및 정리
    cleaned_urls = []
    for url in urls:
        # 여러 URL이 연결되어 있을 경우 분리 시도
        if 'https://' in url and url.count('https://') > 1:
            # 여러 URL이 연결된 경우 분리
            parts = url.split('https://')
            for part in parts:
                if part.strip():
                    cleaned_url = 'https://' + part.strip()
                    if cleaned_url.startswith('https://rg.to/') or cleaned_url.startswith('https://rapidgator.net/'):
                        cleaned_urls.append(cleaned_url)
        else:
            if url.strip():
                cleaned_urls.append(url.strip())

    urls = cleaned_urls
    logger.info(f"정리된 URL 개수: {len(urls)}")
    logger.info(f"새로운 배치 다운로드 시작: {len(urls)}개 URL")

    batch_id = f"batch:{uuid.uuid4()}"
    items = []
    for url in urls:
        item_id = str(uuid.uuid4())
        filename = url.split("/")[-1].split("?")[0] or f"download_{item_id}"
        items.append(
            DownloadItem(id=item_id, url=url, filename=filename)
        )

    batch = DownloadBatch(
        id=batch_id,
        name=f"Batch {time.strftime('%Y-%m-%d %H:%M')}",
        items=items,
        total_items=len(items),
        use_celery=settings.CELERY_ENABLED,
    )

    # Initial progress calculation
    batch.update_progress()
    
    # Save the initial batch state
    save_batch(batch.model_dump())

    try:
        # If celery is enabled, dispatch the batch download task to the background
        if settings.CELERY_ENABLED:
            logger.info(f"Celery 활성화됨. {batch.id}에 대한 태스크를 백그라운드에서 시작합니다.")
            try:
                # Pass the entire batch data as a dictionary
                batch_download_task.delay(batch.model_dump())
            except Exception as e:
                logger.error(f"다운로드 시작 중 오류 발생: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))
        else:
            logger.info(f"Celery 비활성화됨. {batch_id}를 백그라운드 태스크로 실행합니다.")
            background_tasks.add_task(batch_download_task, batch_id, urls)

    except Exception as e:
        logger.error(f"다운로드 시작 중 오류 발생: {e}", exc_info=True)
        batch_data = batch.model_dump()
        batch_data["status"] = "failed"
        batch_data["error_message"] = f"Failed to start download task: {e}"
        save_batch(batch_data)
        raise HTTPException(status_code=500, detail=str(e))

    return batch.model_dump()


@router.get("/batches/{batch_id}", response_model=DownloadBatch)
async def get_batch_status(batch_id: str):
    """배치 다운로드 상태 조회"""
    data = redis_get_batch(batch_id)
    if not data:
        raise HTTPException(status_code=404, detail="Batch not found")

    batch = DownloadBatch.model_validate(data)
    
    if batch.use_celery:
        # Celery 태스크 상태 업데이트
        await update_batch_from_celery(batch)
    
    return batch


@router.delete("/batches")
async def clear_all_batches():
    """모든 배치 키를 Redis에서 제거 (관리용)"""
    keys = list(redis_client.scan_iter("batch:*"))
    deleted = 0
    if keys:
        deleted = redis_client.delete(*keys)
    # broadcast to SSE listeners that everything cleared
    try:
        publish_event("batch:all:events", {"type": "all_cleared"})
    except Exception:
        pass
    return {"deleted_batches": deleted}


@router.get("/batches")
async def list_batches(status: Optional[str] = None):
    """
    모든 배치 목록 조회. status 쿼리 파라미터로 필터링 가능.
    예: /batches?status=active
    """
    logger.info(f"🌐 API 엔드포인트 호출: /batches?status={status}")
    
    try:
        result = list_all_batches(status_filter=status)
        logger.info(f"✅ API 응답 준비 완료: {len(result)}개 배치")
        return result
    except Exception as e:
        logger.error(f"💥 배치 목록 조회 중 오류: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"배치 목록 조회 실패: {str(e)}")


# 디버깅용 엔드포인트 추가
@router.get("/debug/batches")
async def debug_batches(status: Optional[str] = None):
    """🔧 디버깅용 배치 목록 조회"""
    logger.info(f"🛠️ 디버깅 엔드포인트 호출: status={status}")
    
    try:
        # Redis 연결 확인
        redis_info = redis_client.info()
        logger.info(f"🔗 Redis 연결 상태: {redis_info.get('connected_clients', 'unknown')} 클라이언트")
        
        # Redis 키 확인
        keys = list(redis_client.scan_iter("batch:*"))
        logger.info(f"🔑 Redis 키 개수: {len(keys)}")
        
        # 각 키의 내용 확인
        raw_batches = []
        for key in keys:
            raw = redis_client.get(key)
            if raw:
                try:
                    data = json.loads(raw)
                    raw_batches.append({
                        "key": key,
                        "id": data.get("id"),
                        "status": data.get("status"),
                        "total_items": data.get("total_items", 0),
                        "completed_items": data.get("completed_items", 0)
                    })
                except:
                    raw_batches.append({"key": key, "error": "JSON 파싱 실패"})
        
        # list_all_batches 호출
        filtered_batches = list_all_batches(status_filter=status)
        
        return {
            "🔧 debug_info": {
                "status_filter": status,
                "redis_connected": True,
                "redis_keys_count": len(keys),
                "filtered_batches_count": len(filtered_batches)
            },
            "🔑 redis_keys": keys,
            "📦 raw_batches": raw_batches,
            "🎯 filtered_batches": filtered_batches
        }
        
    except Exception as e:
        logger.error(f"💥 디버깅 엔드포인트 오류: {e}", exc_info=True)
        return {
            "error": str(e),
            "redis_connected": False
        }


# -----------------------------------------------------------------------------
# Retry failed items endpoint
# -----------------------------------------------------------------------------


@router.post("/batches/{batch_id}/retry-failed")
async def retry_failed_items(batch_id: str):
    """Requeue all failed items in a batch and return updated batch info."""
    data = redis_get_batch(batch_id)
    if not data:
        raise HTTPException(status_code=404, detail="Batch not found")

    batch = DownloadBatch.model_validate(data)

    retry_count = 0
    for item in batch.items:
        if item.status == "failed":
            # requeue
            task_result = batch_download_task.app.send_task(
                "download_file",
                kwargs={
                    "url": item.url,
                    "batch_id": batch_id,
                    "item_id": item.id,
                    "download_dir": settings.download_path,
                },
            )
            item.task_id = task_result.id
            item.status = "queued"
            retry_count += 1

    if retry_count == 0:
        return {"message": "No failed items to retry", "batch": batch}

    # save and publish event
    save_batch(batch.model_dump(mode="json", by_alias=False))
    publish_event(f"batch:{batch_id}:events", {"type": "retry_started", "count": retry_count})

    return {"message": f"Requeued {retry_count} items", "batch": batch}


# -----------------------------------------------------------------------------
# SSE streaming endpoint
# -----------------------------------------------------------------------------


@router.get("/stream/{batch_id}")
async def stream_batch_updates(batch_id: str):
    """Server-Sent Events endpoint streaming Redis Pub/Sub messages for batch."""

    channel = f"batch:{batch_id}:events"

    async def event_generator():
        redis_async = aioredis.from_url(settings.redis_url, decode_responses=True)
        pubsub = redis_async.pubsub()
        await pubsub.subscribe(channel)
        try:
            # send initial snapshot
            snapshot = redis_get_batch(batch_id)
            if snapshot:
                yield f"data: {json.dumps({'type': 'snapshot', 'data': snapshot})}\n\n"

            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                payload = message["data"]
                yield f"data: {payload}\n\n"
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# -----------------------------------------------------------------------------
# Global SSE stream for all batches
# -----------------------------------------------------------------------------


@router.get("/stream")
async def stream_all_batches():
    """SSE endpoint that streams snapshots/updates for *all* batches."""

    async def event_generator():
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        pubsub = r.pubsub()
        channel = "batch:all:events"
        await pubsub.subscribe(channel)

        # Initial: send list of current batches for initial render
        try:
            keys = await r.keys("batch:*")  # may include non-batch keys but fine
            snapshots = []
            if keys:
                raw_vals = await r.mget(keys)
                for raw in raw_vals:
                    if raw:
                        try:
                            snapshots.append(json.loads(raw))
                        except Exception:
                            pass
            yield f"data: {json.dumps({'type':'init', 'data': snapshots})}\n\n"

            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                yield f"data: {message['data']}\n\n"
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.delete("/batches/{batch_id}")
async def delete_batch(batch_id: str):
    """배치 삭제"""
    data = redis_get_batch(batch_id)
    if not data:
        raise HTTPException(status_code=404, detail="Batch not found")

    batch = DownloadBatch.model_validate(data)
    
    # Celery 태스크 취소 (시도)
    if batch.use_celery:
        try:
            # 각 아이템의 태스크 취소
            for item in batch.items:
                if item.task_id:
                    celery_app.control.revoke(item.task_id, terminate=True)
            
            logger.info(f"Celery 태스크들 취소됨: {batch_id}")
        except Exception as e:
            logger.warning(f"Celery 태스크 취소 실패: {str(e)}")
    
    # 배치 삭제
    redis_client.delete(f"batch:{batch_id}")
    
    return {"message": f"Batch {batch_id} deleted"}


@router.get("/tasks/{task_id}")
async def get_task_status_endpoint(task_id: str):
    """개별 Celery 태스크 상태 조회"""
    try:
        status = get_task_status(task_id)
        return status
    except Exception as e:
        logger.error(f"태스크 상태 조회 실패: {task_id} - {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get task status: {str(e)}")


# Redis에 상태를 반영하도록 템포러리 수정 (추후 Pub/Sub 통합 시 개선)
async def update_batch_from_celery(batch: DownloadBatch):
    """Celery에서 배치 상태를 업데이트"""
    try:
        # 배치의 각 아이템에 대해 Celery 태스크 상태 확인
        # 실제로는 배치 태스크에서 개별 태스크 정보를 가져와야 함
        
        # 배치 태스크 ID를 저장하지 않았으므로, 각 아이템의 태스크 ID를 찾아야 함
        # 이는 실제 구현에서는 배치 태스크 결과에서 가져옴
        
        completed_count = 0
        failed_count = 0
        in_progress_count = 0
        
        for item in batch.items:
            if item.task_id:
                task_status = get_task_status(item.task_id)
                
                if task_status["status"] == "SUCCESS":
                    item.status = "completed"
                    item.progress = 100.0
                    
                    # 결과에서 파일 정보 추출
                    if task_status.get("result"):
                        result = task_status["result"]
                        if isinstance(result, dict):
                            item.filename = result.get("filename")
                            item.file_size = result.get("file_size")
                    
                    completed_count += 1
                    
                elif task_status["status"] == "FAILURE":
                    item.status = "failed"
                    item.error_message = str(task_status.get("result", "Unknown error"))
                    failed_count += 1
                    
                elif task_status["status"] in ["PROGRESS", "RETRY"]:
                    item.status = "downloading"
                    
                    # 진행률 정보 추출
                    if task_status.get("info"):
                        info = task_status["info"]
                        if isinstance(info, dict):
                            current = info.get("current", 0)
                            total = info.get("total", 100)
                            item.progress = (current / total) * 100 if total > 0 else 0
                    
                    in_progress_count += 1
                    
                else:
                    item.status = "pending"
        
        # 배치 전체 상태 업데이트
        batch.completed_items = completed_count
        batch.failed_items = failed_count
        
        total_items = len(batch.items)
        if completed_count == total_items:
            batch.status = "completed"
            batch.completed_at = time.time()
        elif failed_count == total_items:
            batch.status = "failed"
            batch.completed_at = time.time()
        elif completed_count + failed_count == total_items:
            batch.status = "completed_with_errors"
            batch.completed_at = time.time()
        elif in_progress_count > 0:
            batch.status = "downloading"
        else:
            batch.status = "pending"
            
        # Redis에 저장 (상태 스냅샷)
        save_batch(batch.model_dump(mode="json", by_alias=False))
            
    except Exception as e:
        logger.error(f"배치 상태 업데이트 실패: {batch.id} - {str(e)}")


# 기존 백그라운드 태스크 함수 (Celery 사용하지 않을 때)
async def process_batch_download(batch_id: str):
    """배치 다운로드 처리 (백그라운드 태스크)"""
    batch = DownloadBatch.model_validate_json(redis_client.get(f"batch:{batch_id}"))
    if not batch:
        logger.error(f"배치를 찾을 수 없음: {batch_id}")
        return
    
    logger.info(f"배치 다운로드 시작: {batch_id}")
    batch.status = "downloading"
    
    # 여기서는 기존 로직을 유지 (순차 처리)
    # 실제 운영에서는 이 방식보다 Celery를 사용하는 것이 좋음
    
    from ..core.config import settings
    from ..services.rapidgator_client import RapidgatorClient
    
    try:
        # 로그인 확인
        client = RapidgatorClient()
        logged_in = await client.ensure_logged_in()
        if not logged_in:
            logger.error("Rapidgator 로그인 실패")
            batch.status = "failed"
            for item in batch.items:
                item.status = "failed"
                item.error_message = "로그인 실패"
            return
        
        # 각 아이템 다운로드
        for item in batch.items:
            try:
                item.status = "downloading"
                
                # 다운로드 수행
                result = await client.download_file(item.url, settings.download_path)
                
                if result.get("success", False):
                    item.status = "completed"
                    item.filename = result.get("filename")
                    item.file_size = result.get("file_size", 0)
                    item.progress = 100.0
                    batch.completed_items += 1
                else:
                    item.status = "failed"
                    item.error_message = result.get("error", "다운로드 실패")
                    batch.failed_items += 1
                    
            except Exception as e:
                logger.error(f"아이템 다운로드 실패: {item.id} - {str(e)}")
                item.status = "failed"
                item.error_message = str(e)
                batch.failed_items += 1
        
        # 배치 완료 상태 결정
        if batch.failed_items == 0:
            batch.status = "completed"
        elif batch.completed_items == 0:
            batch.status = "failed"
        else:
            batch.status = "completed_with_errors"
        
        batch.completed_at = time.time()
        
        logger.info(f"배치 다운로드 완료: {batch_id} - {batch.completed_items}개 성공, {batch.failed_items}개 실패")
        
    except Exception as e:
        logger.error(f"배치 다운로드 실패: {batch_id} - {str(e)}")
        batch.status = "failed"
        for item in batch.items:
            if item.status == "pending":
                item.status = "failed"
                item.error_message = f"배치 실패: {str(e)}" 

@router.get("/debug/redis_info")
async def redis_info():
    """Get Redis server information."""
    return await redis_client.info()


@router.get("/stats")
async def get_download_stats():
    """Get overall download statistics."""
    batches = list_all_batches() # 모든 배치를 가져오도록 수정
    total_downloads = sum(b.get("total_items", 0) for b in batches)
    completed_downloads = sum(b.get("completed_items", 0) for b in batches)
    
    # Calculate total size (sum of file_size for all completed items)
    total_size_bytes = 0
    for b in batches:
        for item in b.get("items", []):
            if item.get("status") == "completed" and item.get("file_size"):
                total_size_bytes += item.get("file_size", 0)

    # Helper for human-readable size
    def human_readable_size(size, decimal_places=2):
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024.0:
                break
            size /= 1024.0
        return f"{size:.{decimal_places}f} {unit}"

    return {
        "total_downloads": total_downloads,
        "completed_downloads": completed_downloads,
        "active_downloads": sum(1 for b in batches if b.get("status") in ["downloading", "pending"]),
        "total_size_completed": human_readable_size(total_size_bytes)
    }


@router.get("/recent")
async def get_recent_downloads():
    """Get a list of recently completed download batches."""
    batches_data = list_all_batches()
    all_items = []
    for batch in batches_data:
        for item in batch.get("items", []):
            if item.get("status") == "completed":
                # Add batch name to each item for context
                item['batch_name'] = batch.get('name', 'Untitled Batch')
                all_items.append(item)

    # Sort by completion time, most recent first
    all_items.sort(key=lambda x: x.get("completed_at", 0), reverse=True)
    return all_items[:10] # Return latest 10 completed items 
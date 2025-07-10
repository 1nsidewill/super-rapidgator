"""Redis connection and helper utilities for persisting download batches/items.

All higher-level modules (FastAPI endpoints, Celery tasks, etc.) should import
`from super_rapidgator.core.redis_client import redis_client, save_batch, get_batch, publish_event`
so that they share the same connection pool.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional, List

import redis  # type: ignore
from loguru import logger

from .config import settings

__all__ = [
    "redis_client",
    "get_batch_key",
    "save_batch",
    "get_batch",
    "update_batch_status",
    "publish_event",
]

# --------------------------------------------------------------------------------------
# Redis Connection ---------------------------------------------------------------------
# --------------------------------------------------------------------------------------


class _RedisSingleton:
    """Singleton wrapper so every import shares the same connection pool."""

    _client: Optional[redis.Redis] = None

    @classmethod
    def get_client(cls) -> redis.Redis:
        if cls._client is None:
            cls._client = redis.from_url(settings.redis_url, decode_responses=True)
            try:
                cls._client.ping()
                logger.info("Redis 연결 성공: {}", settings.redis_url)
            except redis.ConnectionError as exc:  # pragma: no cover
                logger.error("Redis 연결 실패: {}", exc)
                raise
        return cls._client


redis_client: redis.Redis = _RedisSingleton.get_client()

# --------------------------------------------------------------------------------------
# Helper functions ---------------------------------------------------------------------
# --------------------------------------------------------------------------------------

def get_batch_key(batch_id: str) -> str:
    """Return the Redis key used to store a *single* batch JSON blob."""
    return f"batch:{batch_id}"


# The first iteration stores the entire DownloadBatch (including items) as one JSON blob.
# This keeps implementation simple; we can normalise later if needed.

def save_batch(batch_dict: Dict[str, Any]) -> None:
    """Save or overwrite batch data in Redis.

    Parameters
    ----------
    batch_dict: Mapping representation of DownloadBatch (must include an ``id`` field).
    """
    batch_id = batch_dict.get("id")
    if not batch_id:
        raise ValueError("batch_dict must contain 'id' field")

    key = get_batch_key(batch_id)
    redis_client.set(key, json.dumps(batch_dict))

    # Broadcast snapshot to "all" subscribers for real-time list updates
    try:
        publish_event("batch:all:events", {"type": "snapshot", "data": batch_dict})
    except Exception as exc:
        # Non-fatal; just log
        logger.debug("Failed to broadcast batch snapshot: {}", exc)


def get_batch(batch_id: str) -> Optional[Dict[str, Any]]:
    """Fetch batch data from Redis. Returns None if key missing."""
    raw = redis_client.get(get_batch_key(batch_id))
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:  # pragma: no cover
        logger.warning("Redis batch key %s contains invalid JSON", batch_id)
        return None


def update_batch_status(batch_id: str, status: str) -> None:
    """Update only the status field of a batch in Redis.
    
    Parameters
    ----------
    batch_id: The ID of the batch to update
    status: The new status to set (e.g., 'active', 'completed', 'failed')
    """
    key = get_batch_key(batch_id)
    raw = redis_client.get(key)
    if raw is None:
        logger.warning("Batch {} not found in Redis, cannot update status", batch_id)
        return
    
    try:
        batch_dict = json.loads(raw)
        batch_dict["status"] = status
        
        # Update timestamp based on status
        import time
        if status in ["completed", "failed", "completed_with_errors"]:
            batch_dict["completed_at"] = time.time()
        elif status == "active":
            batch_dict["started_at"] = time.time()
        
        redis_client.set(key, json.dumps(batch_dict))
        
        # Broadcast updated snapshot
        try:
            publish_event("batch:all:events", {"type": "snapshot", "data": batch_dict})
        except Exception as exc:
            logger.debug("Failed to broadcast batch status update: {}", exc)
            
    except json.JSONDecodeError:
        logger.error("Invalid JSON in batch key {}, cannot update status", batch_id)


# --------------------------------------------------------------------------------------
# Pub/Sub ------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------

def publish_event(channel: str, payload: Dict[str, Any]) -> None:
    """Publish a JSON event to a Redis Pub/Sub channel (fire-and-forget)."""
    redis_client.publish(channel, json.dumps(payload)) 


def flush_all_data():
    """
    Deletes all keys from the current Redis database.
    Use with caution, as this is a destructive operation.
    """
    try:
        r = _RedisSingleton.get_client()
        r.flushdb()
        logger.warning("All data has been flushed from the Redis database.")
        return True
    except Exception as e:
        logger.error(f"Failed to flush Redis database: {e}", exc_info=True)
        return False 
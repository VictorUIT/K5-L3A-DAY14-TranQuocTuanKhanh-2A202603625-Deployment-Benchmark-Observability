"""
Rate limiting (tiêu chí 7).

  • Mỗi API key tối đa RATE_LIMIT_PER_MINUTE request trong 60 giây (sliding window)
  • Vượt giới hạn → HTTP 429 kèm header Retry-After
  • State lưu trong Redis (sorted set) → mọi worker / instance dùng chung, còn sau restart
"""
import hashlib
import time
import uuid

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60


def check_rate_limit(key: str) -> None:
    # Hash API key để không lưu key thô trong Redis.
    bucket = "ratelimit:" + hashlib.sha256(key.encode()).hexdigest()[:16]
    now = time.time()
    limit = settings.rate_limit_per_minute

    pipe = r.pipeline(transaction=True)
    pipe.zremrangebyscore(bucket, 0, now - WINDOW_SECONDS)
    pipe.zcard(bucket)
    _, count = pipe.execute()

    if count >= limit:
        oldest = r.zrange(bucket, 0, 0, withscores=True)
        retry_after = int(WINDOW_SECONDS - (now - oldest[0][1])) + 1 if oldest else WINDOW_SECONDS
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: {limit} requests per {WINDOW_SECONDS}s",
            headers={"Retry-After": str(max(retry_after, 1))},
        )

    pipe = r.pipeline(transaction=True)
    pipe.zadd(bucket, {f"{now}:{uuid.uuid4().hex[:8]}": now})
    pipe.expire(bucket, WINDOW_SECONDS + 5)
    pipe.execute()

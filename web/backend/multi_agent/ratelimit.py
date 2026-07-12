"""Rate limiting : compteur partagé Redis (B5) + fallback local par process (B1)."""

import collections
import logging
import time

from . import config as cfg
from . import state

logger = logging.getLogger(__name__)

_rate_buckets: dict[str, collections.deque] = {}
_RATE_LIMIT = 300
_RATE_WINDOW = 60


def _check_rate_limit_local(client_ip: str) -> bool:
    """In-process fallback when Redis is unavailable (per-worker counter)."""
    now = time.time()
    bucket = _rate_buckets.get(client_ip)
    if bucket is None:
        bucket = collections.deque()
        _rate_buckets[client_ip] = bucket
    while bucket and bucket[0] < now - _RATE_WINDOW:
        bucket.popleft()
    if len(bucket) >= _RATE_LIMIT:
        return False
    bucket.append(now)
    if len(_rate_buckets) > 10000:
        oldest_key = next(iter(_rate_buckets))
        del _rate_buckets[oldest_key]
    return True


async def _check_rate_limit(client_ip: str) -> bool:
    """B5: shared counter in Redis — the limit holds across uvicorn workers.

    Fixed window: INCR + EXPIRE NX (atomic pipeline). Falls back to the
    per-process counter if Redis is down (never blocks all traffic).
    """
    if state.redis_pool is not None:
        try:
            key = f"{cfg.MA_PREFIX}:ratelimit:{client_ip}"
            pipe = state.redis_pool.pipeline()
            pipe.incr(key)
            pipe.expire(key, _RATE_WINDOW, nx=True)
            count, _ = await pipe.execute()
            return int(count) <= _RATE_LIMIT
        except Exception as e:
            logger.warning("Rate limit via Redis failed, local fallback: %s", e)
    return _check_rate_limit_local(client_ip)

import os, time
from collections import defaultdict, deque
from fastapi import HTTPException
_hits = defaultdict(deque)

def check_rate_limit(key: str, limit=60, window=60):
    url = os.getenv("REDIS_URL")
    if url:
        import redis
        client = redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=2)
        bucket = f"rl:{key}:{int(time.time() // window)}"
        count = client.incr(bucket)
        if count == 1: client.expire(bucket, window + 1)
        if count > limit:
            raise HTTPException(429, "Rate limit exceeded", headers={"Retry-After": str(window)})
        return
    now=time.monotonic(); q=_hits[key]
    while q and q[0] <= now-window: q.popleft()
    if len(q)>=limit:
        raise HTTPException(429,"Rate limit exceeded",headers={"Retry-After":str(window)})
    q.append(now)

import json, os
from functools import lru_cache

@lru_cache(maxsize=1)
def client():
    url=os.getenv("REDIS_URL")
    if not url: return None
    import redis
    return redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=2)

def get_json(key):
    c=client()
    if not c: return None
    try:
        value=c.get(key)
        return json.loads(value) if value else None
    except Exception: return None

def set_json(key, value, ttl=60):
    c=client()
    if c:
        try: c.setex(key,ttl,json.dumps(value,default=str))
        except Exception: pass

def delete_pattern(pattern):
    c=client()
    if c:
        try:
            for key in c.scan_iter(match=pattern): c.delete(key)
        except Exception: pass

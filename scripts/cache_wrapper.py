from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

try:
    import redis  # type: ignore
except Exception:
    redis = None

SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = SCRIPT_DIR.parent
DEFAULT_CACHE_DIR = WORKSPACE_DIR / 'out' / 'n1n_cache'


class CacheAdapter:
    def __init__(self, ttl_seconds: int = 1800, cache_dir: str | Path | None = None):
        self.ttl_seconds = ttl_seconds
        self.cache_dir = Path(cache_dir or DEFAULT_CACHE_DIR)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.backend = 'disabled'
        self.client = None
        if redis is not None:
            try:
                client = redis.Redis(host='localhost', port=6379, db=0, socket_connect_timeout=0.3, socket_timeout=0.3)
                client.ping()
                self.client = client
                self.backend = 'redis'
                return
            except Exception:
                self.client = None
        self.backend = 'file'

    def make_key(self, payload: dict[str, Any]) -> str:
        blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.md5(blob.encode('utf-8')).hexdigest()

    def get(self, key: str):
        if self.backend == 'redis' and self.client is not None:
            cached = self.client.get(key)
            if not cached:
                return None
            return json.loads(cached)
        if self.backend == 'file':
            path = self.cache_dir / f'{key}.json'
            if not path.exists():
                return None
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
            except Exception:
                return None
            expires_at = data.get('_expires_at', 0)
            if expires_at and expires_at < time.time():
                try:
                    path.unlink()
                except Exception:
                    pass
                return None
            return data.get('payload')
        return None

    def set(self, key: str, value: dict[str, Any]):
        if self.backend == 'redis' and self.client is not None:
            self.client.setex(key, self.ttl_seconds, json.dumps(value, ensure_ascii=False, default=str))
            return
        if self.backend == 'file':
            path = self.cache_dir / f'{key}.json'
            envelope = {'_expires_at': time.time() + self.ttl_seconds, 'payload': value}
            path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def cached_api_call(
    messages: list[dict[str, Any]],
    model: str,
    api_callable: Callable[[], dict[str, Any]],
    *,
    ttl_seconds: int = 1800,
    cache_dir: str | Path | None = None,
    extra_cache_payload: dict[str, Any] | None = None,
):
    adapter = CacheAdapter(ttl_seconds=ttl_seconds, cache_dir=cache_dir)
    cache_payload = {
        'model': model,
        'messages': messages,
        'extra': extra_cache_payload or {},
    }
    key = adapter.make_key(cache_payload)
    cached = adapter.get(key)
    if cached is not None:
        return cached, {'cache_hit': True, 'cache_key': key, 'cache_backend': adapter.backend}
    response = api_callable()
    adapter.set(key, response)
    return response, {'cache_hit': False, 'cache_key': key, 'cache_backend': adapter.backend}

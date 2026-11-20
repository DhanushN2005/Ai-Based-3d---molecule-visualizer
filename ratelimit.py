"""In-memory sliding-window rate limiting, shared by main.py and the accounts blueprint.

State lives in this process only. With more than one worker, move it to Redis.
"""
import logging
import threading
import time
from collections import defaultdict, deque
from functools import wraps

from flask import has_request_context, jsonify, request

log = logging.getLogger("chemverse")

_hits = defaultdict(deque)
_hits_lock = threading.Lock()


def client_ip():
    return request.remote_addr if has_request_context() else "local"


def allowed(name, limit, window=60):
    """True if this client may make another `name` call (sliding window)."""
    now = time.time()
    with _hits_lock:
        q = _hits[(name, client_ip())]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


def rate_limit(limit, window=60):
    """Decorator: allow `limit` calls per `window` seconds per client IP."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if not allowed(fn.__name__, limit, window):
                log.warning("rate limited %s on %s", client_ip(), fn.__name__)
                return jsonify(success=False, error="Too many requests. Please wait a minute."), 429
            return fn(*a, **kw)
        return wrapper
    return deco

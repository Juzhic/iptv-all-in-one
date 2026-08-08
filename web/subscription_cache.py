# -*- coding: utf-8 -*-
"""Rate limiting and stampede-safe caching for anonymous playlist feeds."""

from __future__ import annotations

import hashlib
import os
import threading
import time
from collections import OrderedDict, defaultdict, deque
from functools import wraps

from flask import Response, jsonify, make_response, request


RATE_LIMIT = 60
RATE_WINDOW_SECONDS = 60
CACHE_TTL_SECONDS = 30
MAX_CACHE_ENTRIES = 128

_state_lock = threading.RLock()
_requests_by_ip = defaultdict(deque)
_cache = OrderedDict()
_key_locks = {}


def _client_ip() -> str:
    if os.environ.get('IPTV_TRUST_PROXY', '').strip() == '1':
        forwarded = request.headers.get('X-Forwarded-For', '')
        if forwarded:
            return forwarded.split(',', 1)[0].strip()
    return request.remote_addr or 'unknown'


def _consume_rate_limit(now=None):
    now = time.monotonic() if now is None else now
    client = _client_ip()
    with _state_lock:
        bucket = _requests_by_ip[client]
        cutoff = now - RATE_WINDOW_SECONDS
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= RATE_LIMIT:
            retry_after = max(1, int(RATE_WINDOW_SECONDS - (now - bucket[0]) + 0.999))
            return False, 0, retry_after
        bucket.append(now)
        return True, RATE_LIMIT - len(bucket), 0


def _cache_key():
    query = tuple(
        (key, tuple(values))
        for key, values in sorted(request.args.lists())
    )
    return request.path, query


def _get_cached(key, now=None):
    now = time.monotonic() if now is None else now
    with _state_lock:
        item = _cache.get(key)
        if not item:
            return None
        if now - item['created_at'] >= CACHE_TTL_SECONDS:
            _cache.pop(key, None)
            return None
        _cache.move_to_end(key)
        return dict(item)


def _response_from_entry(entry, remaining):
    etag = entry['etag']
    headers = dict(entry['headers'])
    headers.update({
        'Cache-Control': f'public, max-age={CACHE_TTL_SECONDS}',
        'X-RateLimit-Limit': str(RATE_LIMIT),
        'X-RateLimit-Remaining': str(remaining),
    })
    if request.if_none_match and request.if_none_match.contains(etag):
        response = Response(status=304, headers=headers)
    else:
        response = Response(entry['body'], status=entry['status'], headers=headers)
    response.set_etag(etag)
    return response


def anonymous_feed(view):
    """Wrap an anonymous TXT/M3U route with rate limiting, ETag and cache."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        allowed, remaining, retry_after = _consume_rate_limit()
        if not allowed:
            response = jsonify({'ok': False, 'error': '订阅请求过于频繁，请稍后重试'})
            response.status_code = 429
            response.headers.update({
                'Retry-After': str(retry_after),
                'X-RateLimit-Limit': str(RATE_LIMIT),
                'X-RateLimit-Remaining': '0',
            })
            return response

        key = _cache_key()
        cached = _get_cached(key)
        if cached:
            return _response_from_entry(cached, remaining)

        with _state_lock:
            generation_lock = _key_locks.setdefault(key, threading.Lock())
        with generation_lock:
            cached = _get_cached(key)
            if cached:
                return _response_from_entry(cached, remaining)

            response = make_response(view(*args, **kwargs))
            if response.status_code != 200:
                response.headers['X-RateLimit-Limit'] = str(RATE_LIMIT)
                response.headers['X-RateLimit-Remaining'] = str(remaining)
                return response

            response.direct_passthrough = False
            body = response.get_data()
            etag = hashlib.sha256(body).hexdigest()
            kept_headers = {
                name: value
                for name, value in response.headers.items()
                if name.lower() in {'content-type', 'content-disposition', 'content-language'}
            }
            entry = {
                'created_at': time.monotonic(),
                'status': response.status_code,
                'body': body,
                'headers': kept_headers,
                'etag': etag,
            }
            with _state_lock:
                _cache[key] = entry
                _cache.move_to_end(key)
                while len(_cache) > MAX_CACHE_ENTRIES:
                    old_key, _ = _cache.popitem(last=False)
                    _key_locks.pop(old_key, None)
            return _response_from_entry(entry, remaining)
    return wrapped


def _reset_for_tests():
    with _state_lock:
        _requests_by_ip.clear()
        _cache.clear()
        _key_locks.clear()

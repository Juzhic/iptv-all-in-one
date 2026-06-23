# network.py
import asyncio
import logging
import aiohttp
from aiohttp.resolver import ThreadedResolver
from .config_bridge import GLOBAL_CONCURRENCY

logger = logging.getLogger('iptv_scan')


# ==================== 延迟绑定循环的全局信号量 ====================
class GlobalSemaphore:
    """每次进入 async with 时自动适配当前运行循环的信号量"""
    def __init__(self):
        self._sem = None
        self._loop = None

    def _get_sem(self):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.Semaphore(GLOBAL_CONCURRENCY)
        if self._sem is None or self._loop is not loop:
            self._sem = asyncio.Semaphore(GLOBAL_CONCURRENCY)
            self._loop = loop
        return self._sem

    async def __aenter__(self):
        sem = self._get_sem()
        return await sem.__aenter__()

    async def __aexit__(self, *args):
        sem = self._get_sem()
        return await sem.__aexit__(*args)


global_sem = GlobalSemaphore()


# ==================== HTTP 会话工厂 ====================
def get_session(limit=50, timeout=15, force_close=False):
    connector = aiohttp.TCPConnector(
        limit=limit, limit_per_host=10, force_close=force_close,
        enable_cleanup_closed=True, ttl_dns_cache=300, use_dns_cache=True,
        resolver=ThreadedResolver()
    )
    timeout_obj = aiohttp.ClientTimeout(total=timeout, connect=3)
    return aiohttp.ClientSession(connector=connector, timeout=timeout_obj,
                                 cookie_jar=aiohttp.DummyCookieJar())


async def quick_http_check(session, url, min_bytes=4096, timeout=4):
    """Quick HTTP check returning a result dict.

    Returns:
        dict: ``alive`` (bool), ``status`` (int), ``time_ms`` (float),
              ``bytes`` (int).
    """
    result = {'alive': False, 'status': 0, 'time_ms': 0.0, 'bytes': 0}
    try:
        from datetime import datetime
        start = datetime.now()
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=timeout),
            allow_redirects=True,
        ) as r:
            result['status'] = r.status
            if r.status != 200:
                result['time_ms'] = (datetime.now() - start).total_seconds() * 1000
                return result
            total = 0
            async for chunk in r.content.iter_chunked(2048):
                total += len(chunk)
                if total >= min_bytes:
                    result['alive'] = True
                    result['bytes'] = total
                    result['time_ms'] = (datetime.now() - start).total_seconds() * 1000
                    return result
            result['alive'] = total > 0
            result['bytes'] = total
            result['time_ms'] = (datetime.now() - start).total_seconds() * 1000
            return result
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
        return result

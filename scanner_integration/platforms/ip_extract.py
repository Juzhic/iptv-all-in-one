# -*- coding: utf-8 -*-
"""IP 提取与 C 段扫描模块。"""

import asyncio
import contextvars
import ipaddress
import random
import time
from collections import OrderedDict

import aiohttp

from .. import config_bridge
from ..network import global_sem, get_session
from ..logger_bridge import logger
from .shared import (
    _parse_channels_payload, _extract_cache_key, _get_extract_cache,
    _set_extract_cache, _stats_add,
)


async def extract_channels_from_ip(ip, port, session, prov="", city="", timeout=5):
    """探测单个 IP 的常见 IPTV 接口，提取频道列表。"""
    # SSRF protection: reject private/internal IPs
    try:
        addr = ipaddress.ip_address(ip)
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_multicast or addr.is_unspecified:
            return []
    except ValueError:
        return []

    cache_key = _extract_cache_key(ip, port, timeout)
    cached = _get_extract_cache(cache_key)
    if cached is not None:
        return cached

    candidate_urls = [
        f"http://{ip}:{port}/iptv/live/zh_cn.js",
        f"http://{ip}:{port}/iptv/live/1000.json?key=txiptv",
        f"http://{ip}:{port}/iptv/live/1000.json",
        f"http://{ip}:80/iptv/live/1000.json?key=txiptv",
        f"http://{ip}:8080/iptv/live/1000.json?key=txiptv",
        f"http://{ip}:{port}/ZHGXTV/Public/json/live_interface.txt",
        f"http://{ip}:{port}/streamer/list",
        f"http://{ip}:{port}/api/channels",
        f"http://{ip}:{port}/channels",
        f"http://{ip}:{port}/channel_list.json",
        f"http://{ip}:{port}/getChannelList",
        f"http://{ip}:{port}/api/live/channels",
        f"http://{ip}:{port}/live/channels.json",
        f"http://{ip}:{port}/playlist?profile=pass",
    ]
    async with global_sem:
        for url in candidate_urls:
            try:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(timeout),
                    allow_redirects=False
                ) as r:
                    if r.status != 200:
                        continue
                    result = _parse_channels_payload(await r.read(), str(r.url), prov, city, ip)
                    if result:
                        _set_extract_cache(cache_key, result)
                        return result
            except Exception as e:
                logger.debug(f"[extract] {ip}:{port} 失败: {e}")
                continue
    _set_extract_cache(cache_key, [])
    return []


def get_c_segment_ips(ip):
    """获取 IP 所在 C 段的全部 254 个 IP。"""
    parts = ip.split('.')
    if len(parts) != 4:
        return []
    return [f"{'.'.join(parts[:3])}.{i}" for i in range(1, 255)]


def _pick_c_segment_ips(base_ip, limit):
    """Pick nearby hosts first, while never probing the seed host again."""
    try:
        limit = max(1, int(limit))
        base_last = int(base_ip.split('.')[-1])
    except (TypeError, ValueError, IndexError):
        return []

    all_ips = [ip for ip in get_c_segment_ips(base_ip) if ip != base_ip]
    if len(all_ips) <= limit:
        return all_ips

    neighbors = [
        ip for ip in all_ips
        if abs(int(ip.rsplit('.', 1)[-1]) - base_last) <= 10
    ]
    selected = neighbors[:limit]
    if len(selected) < limit:
        selected_set = set(selected)
        others = [ip for ip in all_ips if ip not in selected_set]
        selected.extend(random.sample(others, min(limit - len(selected), len(others))))
    return selected


async def c_segment_scan(base_ip, port, session, limit=50):
    """扫描单个 C 段。"""
    scanned = _pick_c_segment_ips(base_ip, limit)
    logger.info(f"[C段] {base_ip}/24 扫描 {len(scanned)} 个IP")
    entries, cnt = [], 0
    for i in range(0, len(scanned), 50):
        batch = scanned[i:i+50]
        tasks = [extract_channels_from_ip(ip, port, session, timeout=3) for ip in batch]
        for lst in await asyncio.gather(*tasks, return_exceptions=True):
            if isinstance(lst, list) and lst:
                entries.extend(lst)
                cnt += 1
        if i + 50 < len(scanned):
            await asyncio.sleep(0.5)
    logger.info(f"[C段] 完成：{cnt}个IP有数据，{len(entries)}个频道")
    return entries


# C段缓存（带 TTL 和最大容量限制，使用 OrderedDict 保证 O(1) 操作）
class _TTLCache:
    def __init__(self, ttl=300, max_size=1000):
        self._cache = OrderedDict()
        self._ttl = ttl
        self._max_size = max_size

    def get(self, key):
        if key in self._cache:
            ts, val = self._cache[key]
            if time.time() - ts < self._ttl:
                self._cache.move_to_end(key)
                return val
            del self._cache[key]
        return None

    def set(self, key, val):
        if key in self._cache:
            self._cache.move_to_end(key)
        elif len(self._cache) >= self._max_size:
            self._cache.popitem(last=False)
        self._cache[key] = (time.time(), val)


_c_segment_cache = _TTLCache(ttl=300, max_size=1000)
_c_segment_budget_context = contextvars.ContextVar(
    'c_segment_budget_context', default=None
)


class CScanBudget:
    """Shared C-segment budget for one collection run.

    A platform/profile invocation has its own small allowance, while all of
    them reserve from the same scan-wide segment and IP budget.  Reservations
    happen under one lock so concurrent platform tasks cannot overrun the
    configured maximums.
    """

    def __init__(self, scan_config=None, cache=None):
        cfg = scan_config or config_bridge.get_scan_config()
        self.max_segments = max(1, int(cfg.get('c_segment_max_segments', 8)))
        self.max_ips = max(1, int(cfg.get('c_segment_max_total_ips', 200)))
        self.max_source_segments = max(
            1, int(cfg.get('c_segment_per_source_max_segments', 2))
        )
        self.max_source_ips = max(
            1, int(cfg.get('c_segment_per_source_max_ips', 50))
        )
        self.cache = cache or _c_segment_cache
        self._lock = asyncio.Lock()
        self._segments_used = 0
        self._ips_used = 0
        self._source_usage = {}

    @property
    def segments_used(self):
        return self._segments_used

    @property
    def ips_used(self):
        return self._ips_used

    async def reserve(self, source_key, plans):
        """Reserve planned ``(segment, port, ips)`` probes atomically."""
        selected = []
        summary = {
            'segments': 0,
            'ips': 0,
            'cache_skipped': 0,
            'budget_skipped': 0,
        }
        async with self._lock:
            usage = self._source_usage.setdefault(
                source_key, {'segments': 0, 'ips': 0}
            )
            for segment, port, ips in plans:
                cache_key = (segment, port)
                if self.cache.get(cache_key) is not None:
                    summary['cache_skipped'] += 1
                    continue
                if (
                    self._segments_used >= self.max_segments
                    or usage['segments'] >= self.max_source_segments
                    or self._ips_used >= self.max_ips
                    or usage['ips'] >= self.max_source_ips
                ):
                    summary['budget_skipped'] += 1
                    continue

                allowed = min(
                    len(ips),
                    self.max_ips - self._ips_used,
                    self.max_source_ips - usage['ips'],
                )
                if allowed <= 0:
                    summary['budget_skipped'] += 1
                    continue

                self.cache.set(cache_key, True)
                accepted = ips[:allowed]
                selected.extend((ip, port) for ip in accepted)
                self._segments_used += 1
                self._ips_used += len(accepted)
                usage['segments'] += 1
                usage['ips'] += len(accepted)
                summary['segments'] += 1
                summary['ips'] += len(accepted)
        return selected, summary


def begin_c_segment_budget(scan_config=None):
    """Install a scan-wide C-segment budget in the current async context."""
    return _c_segment_budget_context.set(CScanBudget(scan_config))


def end_c_segment_budget(token):
    """Remove the scan-wide C-segment budget after collection completes."""
    _c_segment_budget_context.reset(token)


async def smart_c_segment_scan(successful_ips, session, stats=None, source_key=None):
    """基于已成功 IP 智能扫描邻近 C 段。"""
    if not config_bridge.get_scan_config().get("enable_c_scan"):
        return []
    scan_config = config_bridge.get_scan_config()
    cs_limit = scan_config.get("c_scan_limit", 50)
    segs = {}
    for ip, port in successful_ips:
        seg = '.'.join(ip.split('.')[:3])
        key = (seg, port)
        if key not in segs:
            segs[key] = (ip, port)

    plans = [
        (segment, port, _pick_c_segment_ips(ip, cs_limit))
        for (segment, port), (ip, _port) in segs.items()
    ]
    budget = _c_segment_budget_context.get() or CScanBudget(scan_config)
    source_key = source_key or (id(stats) if isinstance(stats, dict) else 'standalone')
    all_ip, summary = await budget.reserve(source_key, plans)
    _stats_add(stats, 'c_segment_segments', summary['segments'])
    _stats_add(stats, 'c_segment_ips', summary['ips'])
    _stats_add(stats, 'c_segment_cache_skipped', summary['cache_skipped'])
    _stats_add(stats, 'c_segment_budget_skipped', summary['budget_skipped'])
    if summary['cache_skipped']:
        logger.debug(f"[C段] 跳过近期已扫描的 {summary['cache_skipped']} 个网段/端口")
    logger.info(
        f"[C段] 本来源预留 {summary['segments']} 段、{summary['ips']} 个IP；"
        f"全局已用 {budget.segments_used}/{budget.max_segments} 段，"
        f"{budget.ips_used}/{budget.max_ips} 个IP"
    )
    entries, cnt = [], 0
    for i in range(0, len(all_ip), 50):
        batch = all_ip[i:i+50]
        tasks = [extract_channels_from_ip(ip, p, session, timeout=3) for ip, p in batch]
        for lst in await asyncio.gather(*tasks, return_exceptions=True):
            if isinstance(lst, list) and lst:
                entries.extend(lst)
                cnt += 1
        if i + 50 < len(all_ip):
            await asyncio.sleep(0.5)
    seen = set()
    uniq = []
    for e in entries:
        if e['url'] not in seen:
            seen.add(e['url'])
            uniq.append(e)
    logger.info(f"[C段] 发现 {len(uniq)} 个新频道")
    return uniq

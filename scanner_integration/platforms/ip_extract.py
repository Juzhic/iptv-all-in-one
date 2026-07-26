# -*- coding: utf-8 -*-
"""IP 提取与 C 段扫描模块。"""

import asyncio
import ipaddress
import random
import time
from collections import OrderedDict

import aiohttp

from . import config_bridge
from .network import global_sem, get_session
from .logger_bridge import logger
from .shared import _parse_channels_payload, _extract_cache_key, _get_extract_cache, _set_extract_cache


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


async def c_segment_scan(base_ip, port, session, limit=50):
    """扫描单个 C 段。"""
    all_ips = get_c_segment_ips(base_ip)
    if len(all_ips) > limit:
        base_last = int(base_ip.split('.')[-1])
        neighbors = [ip for ip in all_ips if abs(int(ip.split('.')[-1]) - base_last) <= 10]
        others = [ip for ip in all_ips if ip not in neighbors]
        scanned = neighbors + random.sample(others, min(limit - len(neighbors), len(others)))
    else:
        scanned = all_ips
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


async def smart_c_segment_scan(successful_ips, session):
    """基于已成功 IP 智能扫描邻近 C 段。"""
    if not config_bridge.get_scan_config().get("enable_c_scan"):
        return []
    cs_limit = config_bridge.get_scan_config().get("c_scan_limit", 50)
    max_seg = config_bridge.get_scan_config().get("c_segment_max_segments", 8)
    max_total = config_bridge.get_scan_config().get("c_segment_max_total_ips", 200)
    segs = {}
    for ip, port in successful_ips:
        seg = '.'.join(ip.split('.')[:3])
        if seg not in segs:
            segs[seg] = (ip, port)
    now = time.time()
    fresh_segs = {}
    for seg, (ip, port) in segs.items():
        last = _c_segment_cache.get(seg)
        if last is None:
            fresh_segs[seg] = (ip, port)
            _c_segment_cache.set(seg, now)
        else:
            logger.debug(f"[C段] 跳过近期已扫描的 {seg}/24")
    segs = fresh_segs
    if len(segs) > max_seg:
        segs = dict(list(segs.items())[:max_seg])
    all_ip = []
    for ip, port in segs.values():
        ips = get_c_segment_ips(ip)
        if len(ips) > cs_limit:
            bl = int(ip.split('.')[-1])
            neighbors = [x for x in ips if abs(int(x.split('.')[-1]) - bl) <= 10]
            others = [x for x in ips if x not in neighbors]
            scanned = neighbors + random.sample(others, min(cs_limit - len(neighbors), len(others)))
        else:
            scanned = ips
        all_ip.extend((x, port) for x in scanned)
    if len(all_ip) > max_total:
        logger.info(f"[C段] 限制IP总数 {max_total}")
        all_ip = random.sample(all_ip, max_total)
    logger.info(f"[C段] 最终扫描 {len(all_ip)} 个IP")
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

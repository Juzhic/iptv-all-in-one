# -*- coding: utf-8 -*-
"""
ISP Intelligence 模块。
分析历史扫描数据，发现 IPTV 密集的 IP 段（/24 C-segment），
然后对这些热点段进行主动扫描以发现新频道。
"""
import asyncio
import random
import ipaddress
from collections import Counter
from urllib.parse import urlparse

import aiohttp

from . import config_bridge
from .logger_bridge import logger


def _safe_float(value, default=0.0):
    try:
        if value in (None, ''):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _url_port(url):
    try:
        parsed = urlparse(url or '')
        if parsed.port:
            return parsed.port
        if parsed.scheme == 'https':
            return 443
        if parsed.scheme == 'http':
            return 80
    except ValueError:
        pass
    return None


def _row_quality_score(row, min_stability):
    stability = _safe_float(row.get('stability'), 0)
    if stability < min_stability:
        return 0
    bandwidth = _safe_float(row.get('bandwidth'), 0)
    delay = _safe_float(row.get('delay'), 0)
    failures = _safe_float(row.get('consecutive_failures'), 0)
    status = (row.get('quality_status') or '').lower()

    status_bonus = {
        'good': 8,
        'poor': 2,
        'pending': 1,
        'unreachable': -6,
        'circuit_breaker_skipped': -6,
    }.get(status, 0)
    delay_bonus = max(0, 3 - delay / 700) if delay else 1
    bandwidth_bonus = min(8, bandwidth / 400) if bandwidth else 0
    score = stability / 10 + bandwidth_bonus + delay_bonus + status_bonus - failures * 2
    return max(0, score)


def _public_ipv4(value):
    try:
        addr = ipaddress.ip_address(value)
        if addr.version != 4:
            return None
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_multicast or addr.is_unspecified:
            return None
        return str(addr)
    except ValueError:
        return None


async def analyze_ip_clusters():
    """从 persistent_scan_results 中读取所有 source_ip，按 /24 分组统计频道数。

    Returns:
        list[tuple[str, int]]: 按频道数降序排列的 (segment, channel_count) 列表。
        segment 格式为 "x.y.z"（不含末尾的点）。
    """
    import database as _db

    conn = _db._get_conn()
    rows = conn.execute(
        "SELECT source_ip FROM persistent_scan_results WHERE source_ip IS NOT NULL AND source_ip != ''"
    ).fetchall()

    if not rows:
        logger.info("[ISP] 持久化结果中无 source_ip 数据")
        return []

    segment_counter = Counter()
    for row in rows:
        ip = row['source_ip']
        if not ip:
            continue
        parts = ip.split('.')
        if len(parts) != 4:
            continue
        segment = '.'.join(parts[:3])
        segment_counter[segment] += 1

    sorted_segments = segment_counter.most_common()
    logger.info(f"[ISP] 分析完成，共 {len(sorted_segments)} 个 C 段，"
                f"最密集段: {sorted_segments[0] if sorted_segments else 'N/A'}")
    return sorted_segments


async def analyze_quality_clusters(min_stability=None):
    """按历史质量加权分析高价值 C 段。

    Returns:
        list[dict]: score 降序的热点段元数据，包含端口和历史成功 IP。
    """
    import database as _db

    cfg = config_bridge.get_scan_config()
    if min_stability is None:
        min_stability = cfg.get('quality_source_min_stability', 45)

    conn = _db._get_conn()
    rows = conn.execute(
        """SELECT source_ip, url, stability, delay, bandwidth,
                  quality_status, consecutive_failures
           FROM persistent_scan_results
           WHERE deleted_at IS NULL
             AND source_ip IS NOT NULL
             AND source_ip != ''"""
    ).fetchall()

    segments = {}
    for row in rows:
        ip = _public_ipv4(row.get('source_ip'))
        if not ip:
            continue
        score = _row_quality_score(row, min_stability)
        if score <= 0:
            continue
        segment = '.'.join(ip.split('.')[:3])
        item = segments.setdefault(segment, {
            'segment': segment,
            'score': 0.0,
            'channel_count': 0,
            'good_count': 0,
            'hosts': Counter(),
            'ports': Counter(),
            'stability_total': 0.0,
        })
        item['score'] += score
        item['channel_count'] += 1
        item['stability_total'] += _safe_float(row.get('stability'), 0)
        if (row.get('quality_status') or '').lower() == 'good':
            item['good_count'] += 1
        item['hosts'][ip] += score
        port = _url_port(row.get('url'))
        if port:
            item['ports'][port] += score

    result = []
    for item in segments.values():
        count = max(1, item['channel_count'])
        result.append({
            'segment': item['segment'],
            'score': round(item['score'], 2),
            'channel_count': item['channel_count'],
            'good_count': item['good_count'],
            'avg_stability': round(item['stability_total'] / count, 1),
            'hosts': [host for host, _ in item['hosts'].most_common(8)],
            'ports': [port for port, _ in item['ports'].most_common(6)],
        })

    result.sort(key=lambda x: (x['score'], x['good_count'], x['avg_stability']), reverse=True)
    logger.info(f"[ISP] 质量热点分析完成，共 {len(result)} 个 C 段")
    return result


async def get_quality_hot_segments(min_score=None, top_n=None):
    cfg = config_bridge.get_scan_config()
    if min_score is None:
        min_score = cfg.get('quality_hotspot_min_score', 8)
    if top_n is None:
        top_n = 30
    all_segments = await analyze_quality_clusters()
    result = [item for item in all_segments if item['score'] >= min_score][:top_n]
    logger.info(
        f"[ISP] 质量热点筛选: min_score={min_score}, "
        f"返回 {len(result)} 个"
    )
    return result


async def get_hot_segments(min_channels=None, top_n=None):
    """返回频道数 >= min_channels 的热点 C 段（最多 top_n 个）。

    Args:
        min_channels: 最低频道阈值，默认读 config_bridge 配置。
        top_n: 返回数量上限，默认读 config_bridge 配置（默认 50）。

    Returns:
        list[tuple[str, int]]: 过滤后的 (segment, channel_count) 列表。
    """
    cfg = config_bridge.get_scan_config()
    if min_channels is None:
        min_channels = cfg.get('hot_segment_min_channels', 3)
    if top_n is None:
        top_n = 50  # 固定上限，不受 scan_limit 影响

    all_segments = await analyze_ip_clusters()
    hot = [(seg, cnt) for seg, cnt in all_segments if cnt >= min_channels]
    result = hot[:top_n]
    logger.info(f"[ISP] 热点段筛选: min_channels={min_channels}, "
                f"共 {len(hot)} 个达标，返回 top {len(result)}")
    return result


async def scan_hot_segments(session, limit=None):
    """对热点 C 段进行随机 IP 采样扫描，发现新频道。

    Args:
        session: aiohttp.ClientSession 实例。
        limit: 最大扫描 IP 数，默认读 config_bridge 配置（默认 200）。

    Returns:
        list[dict]: 发现的频道列表。
    """
    from .platforms import extract_channels_from_ip

    cfg = config_bridge.get_scan_config()
    if limit is None:
        limit = cfg.get('hot_segment_scan_limit', 200)

    hot_segments = await get_hot_segments()
    if not hot_segments:
        logger.info("[ISP] 无热点段，跳过扫描")
        return []

    # 计算每段分配的 IP 数量（均匀分配，至少 1 个）
    ips_per_segment = max(1, limit // len(hot_segments))
    total_budget = min(limit, ips_per_segment * len(hot_segments))

    logger.info(f"[ISP] 开始扫描 {len(hot_segments)} 个热点段，"
                f"每段 {ips_per_segment} 个 IP，总预算 {total_budget}")

    # 生成采样 IP 列表
    sample_ips = []
    for seg, _channel_count in hot_segments:
        # 在该段内随机采样 ips_per_segment 个 IP（排除 .0 和 .255）
        available = list(range(1, 255))
        chosen = random.sample(available, min(ips_per_segment, 254))
        for last_octet in chosen:
            sample_ips.append(f"{seg}.{last_octet}")

    random.shuffle(sample_ips)
    sample_ips = sample_ips[:total_budget]

    # 并发扫描
    ports_to_try = config_bridge.get_scan_config().get(
        'scan_ports', [8080, 80, 443, 9981, 8888, 8000, 9090, 3000, 5000, 8443])

    discovered = []
    sem = asyncio.Semaphore(50)

    async def _probe(ip):
        async with sem:
            for port in ports_to_try:
                try:
                    channels = await asyncio.wait_for(
                        extract_channels_from_ip(ip, port, session, timeout=3),
                        timeout=8
                    )
                    if channels:
                        return channels
                except (asyncio.TimeoutError, Exception):
                    continue
            return []

    tasks = [_probe(ip) for ip in sample_ips]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    seen_urls = set()
    for result in results:
        if isinstance(result, Exception):
            continue
        if not isinstance(result, list):
            continue
        for ch in result:
            url = ch.get('url', '')
            if url and url not in seen_urls:
                seen_urls.add(url)
                ch['scan_source'] = 'ISP Intelligence'
                discovered.append(ch)

    logger.info(f"[ISP] 扫描完成，检查 {len(sample_ips)} 个 IP，"
                f"发现 {len(discovered)} 个频道")
    return discovered


async def scan_quality_hotspots(session, limit=None):
    """围绕历史高质量源的网段做定向补源。"""
    from .platforms import extract_channels_from_ip

    cfg = config_bridge.get_scan_config()
    if limit is None:
        limit = cfg.get('quality_hotspot_scan_limit', 120)

    hot_segments = await get_quality_hot_segments()
    if not hot_segments:
        logger.info("[ISP] 无质量热点段，跳过质量补源")
        return []

    per_segment = max(2, limit // len(hot_segments))
    default_ports = cfg.get(
        'scan_ports', [8080, 80, 443, 9981, 8888, 8000, 9090, 3000, 5000, 8443])

    candidates = []
    seen = set()
    for item in hot_segments:
        segment = item['segment']
        preferred_hosts = []
        for host in item.get('hosts', []):
            try:
                last = int(host.split('.')[-1])
            except (ValueError, IndexError):
                continue
            for offset in (0, -1, 1, -2, 2, -3, 3):
                value = last + offset
                if 1 <= value <= 254:
                    preferred_hosts.append(f"{segment}.{value}")

        random_hosts = [f"{segment}.{i}" for i in random.sample(range(1, 255), min(254, per_segment * 2))]
        hosts = []
        for host in preferred_hosts + random_hosts:
            if host in hosts:
                continue
            hosts.append(host)
            if len(hosts) >= per_segment:
                break

        ports = []
        for port in list(item.get('ports') or []) + default_ports:
            try:
                port = int(port)
            except (TypeError, ValueError):
                continue
            if port not in ports:
                ports.append(port)
            if len(ports) >= 6:
                break

        for host in hosts:
            for port in ports:
                key = (host, port)
                if key in seen:
                    continue
                seen.add(key)
                candidates.append((host, port, item))
                if len(candidates) >= limit:
                    break
            if len(candidates) >= limit:
                break
        if len(candidates) >= limit:
            break

    logger.info(
        f"[ISP] 质量补源开始：热点段 {len(hot_segments)} 个，"
        f"候选 {len(candidates)} 个"
    )

    discovered = []
    seen_urls = set()
    sem = asyncio.Semaphore(40)

    async def _probe(ip, port, item):
        async with sem:
            try:
                channels = await asyncio.wait_for(
                    extract_channels_from_ip(ip, port, session, timeout=4),
                    timeout=10
                )
            except Exception:
                return []
            if not channels:
                return []
            for ch in channels:
                ch['scan_source'] = 'Quality Hotspot'
                ch['discovery_score'] = item.get('score', 0)
            return channels

    results = await asyncio.gather(*[_probe(ip, port, item) for ip, port, item in candidates], return_exceptions=True)
    for result in results:
        if isinstance(result, Exception) or not isinstance(result, list):
            continue
        for ch in result:
            url = ch.get('url', '')
            if url and url not in seen_urls:
                seen_urls.add(url)
                discovered.append(ch)

    logger.info(f"[ISP] 质量补源完成，发现 {len(discovered)} 个频道")
    return discovered

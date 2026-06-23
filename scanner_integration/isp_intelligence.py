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

import aiohttp

from . import config_bridge
from .logger_bridge import logger


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

# -*- coding: utf-8 -*-
"""
扫描结果持久化合并模块。
将每次扫描的 scan_results 合并到 persistent_scan_results（唯一活数据池），
并立即执行一次验证。
"""
import asyncio
import logging

import aiohttp

from . import config_bridge
from .network import get_session

logger = logging.getLogger('scanner.persistence')


async def merge_scan_to_persistent(scan_id):
    """将某次扫描的结果合并到持久化结果表，然后立即验证所有 pending 行。"""
    import db as _db

    # 1. 读取该次扫描的所有结果
    conn = _db._get_conn()
    rows = conn.execute(
        """SELECT name, url, category, province, city, source_ip,
                  resolution, codec, delay, bandwidth, stability
           FROM scan_results WHERE scan_id = ?""",
        (scan_id,)
    ).fetchall()

    if not rows:
        logger.info(f"[Persistence] scan {scan_id} 无结果可合并")
        return

    # 2. 从 scan_runs 获取平台信息
    run_row = conn.execute(
        "SELECT platforms_used FROM scan_runs WHERE scan_id = ?",
        (scan_id,)
    ).fetchone()
    platform_str = ''
    if run_row and run_row['platforms_used']:
        platform_str = run_row['platforms_used']

    # 提取主平台名称（取第一个）
    main_platform = _extract_main_platform(platform_str)

    # 3. 批量 UPSERT
    merge_rows = []
    for r in rows:
        merge_rows.append({
            'url': r['url'],
            'name': r['name'],
            'category': r['category'] or '',
            'province': r['province'] or '',
            'city': r['city'] or '',
            'source_ip': r['source_ip'] or '',
            'platform': main_platform,
            'resolution': r['resolution'] or '',
            'codec': r['codec'] or '',
            'delay': r['delay'],
            'bandwidth': r['bandwidth'],
            'stability': r['stability'] or 0,
        })

    _db.upsert_persistent_results(merge_rows)
    logger.info(f"[Persistence] 合并 {len(merge_rows)} 条记录到持久化结果集")

    # 4. 立即验证所有 pending 行
    await _validate_pending()


def _extract_main_platform(platforms_used_str):
    """从 platforms_used 字符串提取主平台名。"""
    if not platforms_used_str:
        return '未知'
    # 格式可能是 "['quake', 'hunter']" 或 "quake,hunter"
    s = platforms_used_str.strip("[]'\" ")
    first = s.split(',')[0].strip().strip("'\"")
    platform_map = {
        'quake': 'Quake 360',
        'hunter': 'Hunter',
        'daydaymap': 'DayDayMap',
        'zhgx': 'ZHGX',
        'jsmpeg': 'JSMpeg',
        'tvheadend': 'Tvheadend',
    }
    return platform_map.get(first.lower(), first or '未知')


async def _validate_pending():
    """对所有 pending 的持久化结果执行快速验证。"""
    import db as _db

    pending = _db.get_pending_persistent()
    if not pending:
        logger.info("[Persistence] 无待验证记录")
        return

    logger.info(f"[Persistence] 开始验证 {len(pending)} 条待验证记录...")
    sem = asyncio.Semaphore(30)
    verified = 0
    good = 0
    poor = 0
    failed = 0

    timeout = aiohttp.ClientTimeout(total=5)
    async with get_session(limit=30, timeout=timeout) as session:
        async def check_one(item):
            nonlocal verified, good, poor, failed
            url = item['url']
            if not url.startswith(('http://', 'https://')):
                _db.update_persistent_check(url, ok=False)
                failed += 1
                return

            async with sem:
                # 快速连接检查
                ok = await _quick_check(session, url)
                if not ok:
                    _db.update_persistent_check(url, ok=False)
                    failed += 1
                    return

                # 使用扫描时已有的指标判定质量
                stability = item.get('stability', 0)
                delay = item.get('delay')
                bandwidth = item.get('bandwidth')
                _db.update_persistent_check(
                    url, ok=True,
                    stability=stability,
                    delay=delay,
                    bandwidth=bandwidth,
                    resolution=item.get('resolution'),
                    codec=item.get('codec'),
                )
                verified += 1
                if stability >= 60:
                    good += 1
                elif stability >= 30:
                    poor += 1

        await asyncio.gather(*[check_one(item) for item in pending])

    logger.info(f"[Persistence] 验证完成: 通过={verified}, good={good}, poor={poor}, 失败={failed}")


async def _quick_check(session, url):
    """快速检查 URL 是否可连接。"""
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=4),
                               allow_redirects=True) as r:
            if r.status != 200:
                return False
            total = 0
            async for chunk in r.content.iter_chunked(2048):
                total += len(chunk)
                if total >= 4096:
                    return True
            return total > 0
    except Exception:
        return False

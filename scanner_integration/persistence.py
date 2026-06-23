# -*- coding: utf-8 -*-
"""
扫描结果持久化合并模块。
将每次扫描的 scan_results 合并到 persistent_scan_results（唯一活数据池），
并立即执行一次验证。
"""
import asyncio
import logging

from . import config_bridge
from .network import get_session, quick_http_check

logger = logging.getLogger('scanner.persistence')


async def merge_scan_to_persistent(scan_id):
    """将某次扫描的结果合并到持久化结果表，然后立即验证所有 pending 行。"""
    import database as _db

    # 1. 读取该次扫描的所有结果（包含 per-channel platform）
    conn = _db._get_conn()
    rows = conn.execute(
        """SELECT name, url, category, province, city, source_ip,
                  platform, resolution, codec, delay, bandwidth, stability
           FROM scan_results WHERE scan_id = %s""",
        (scan_id,)
    ).fetchall()

    if not rows:
        logger.info(f"[Persistence] scan {scan_id} 无结果可合并")
        return

    # 2. 批量 UPSERT（使用每条记录自身的 platform）
    merge_rows = []
    for r in rows:
        merge_rows.append({
            'url': r['url'],
            'name': r['name'],
            'category': r['category'] or '',
            'province': r['province'] or '',
            'city': r['city'] or '',
            'source_ip': r['source_ip'] or '',
            'platform': r['platform'] or '未知',
            'resolution': r['resolution'] or '',
            'codec': r['codec'] or '',
            'delay': r['delay'],
            'bandwidth': r['bandwidth'],
            'stability': r['stability'] or 0,
        })

    _db.upsert_persistent_results(merge_rows)
    logger.info(f"[Persistence] 合并 {len(merge_rows)} 条记录到持久化结果集")

    # 4. 立即验证所有 pending 行（验证失败不影响已合并的数据）
    try:
        await _validate_pending()
    except Exception as e:
        logger.warning(f"[Persistence] 验证过程出错（数据已保留）: {type(e).__name__}: {e}")


async def _validate_pending():
    """对所有 pending 的持久化结果执行快速验证。"""
    import database as _db

    pending = _db.get_pending_persistent()
    if not pending:
        logger.info("[Persistence] 无待验证记录")
        return

    logger.info(f"[Persistence] 开始验证 {len(pending)} 条待验证记录...")
    sem = asyncio.Semaphore(20)
    verified = 0
    good = 0
    poor = 0
    failed = 0
    fail_reasons = {}

    async with get_session(limit=20, timeout=6) as session:
        async def check_one(item):
            nonlocal verified, good, poor, failed
            async with sem:  # 统一限流：含非 http 分支，避免一次性铺开大量协程同步写 DB
                url = item['url']
                if not url.startswith(('http://', 'https://')):
                    _db.update_persistent_check(url, ok=False)
                    failed += 1
                    fail_reasons['non_http'] = fail_reasons.get('non_http', 0) + 1
                    return

                stability = item.get('stability', 0) or 0
                delay = item.get('delay')
                bandwidth = item.get('bandwidth')

                # Channels with stability > 0 already passed deep_check;
                # accept them directly without a redundant HTTP probe.
                if stability > 0:
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
                    return

                # Truly unverified (stability is NULL or 0) – do a quick HTTP check
                ok = await _quick_check(session, url)
                if not ok:
                    _db.update_persistent_check(url, ok=False)
                    failed += 1
                    fail_reasons['http_check_failed'] = fail_reasons.get('http_check_failed', 0) + 1
                    return

                _db.update_persistent_check(
                    url, ok=True,
                    stability=stability,
                    delay=delay,
                    bandwidth=bandwidth,
                    resolution=item.get('resolution'),
                    codec=item.get('codec'),
                )
                verified += 1

        await asyncio.gather(*[check_one(item) for item in pending])

    logger.info(
        f"[Persistence] 验证完成: 通过={verified} (good={good}, poor={poor}), "
        f"失败={failed} {fail_reasons if fail_reasons else ''}"
    )


async def _quick_check(session, url):
    """快速检查 URL 是否可连接。"""
    return quick_http_check(session, url)['alive']

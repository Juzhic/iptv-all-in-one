# -*- coding: utf-8 -*-
"""
定期检测模块。
在后台定期检测 persistent_scan_results 中的所有源，
连续失败达到阈值的自动删除。
"""
import asyncio
import logging

import aiohttp

from . import config_bridge
from .network import get_session

logger = logging.getLogger('scanner.detection')


class DetectionManager:
    """定期检测管理器，运行在 AsyncBridge 的事件循环上。"""

    def __init__(self):
        self._task = None
        self._running = False
        self._last_cycle_at = None
        self._last_cycle_result = None

    @property
    def status(self):
        """返回检测模块当前状态。"""
        return {
            'running': self._running,
            'last_cycle_at': self._last_cycle_at,
            'last_cycle_result': self._last_cycle_result,
        }

    def start(self):
        """启动检测循环。"""
        if self._task and not self._task.done():
            logger.info("[Detection] 检测循环已在运行")
            return
        from . import bridge
        self._running = True
        self._task = bridge.run_background(self._loop())
        logger.info("[Detection] 检测循环已启动")

    def stop(self):
        """停止检测循环。"""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            logger.info("[Detection] 检测循环已停止")

    async def _loop(self):
        """主循环：等待间隔 → 执行检测 → 循环。"""
        # 启动后先等一个间隔再开始第一次检测
        while self._running:
            cfg = config_bridge.get_scan_config()
            interval = cfg.get('detection_interval_minutes', 120)
            if interval <= 0:
                # 间隔为 0 或负数时暂停，60秒后重新检查配置
                await asyncio.sleep(60)
                continue

            logger.info(f"[Detection] 下次检测将在 {interval} 分钟后")
            await asyncio.sleep(interval * 60)

            if not self._running:
                break
            await self._run_detection_cycle()

    async def _run_detection_cycle(self):
        """执行一次完整的检测周期。"""
        import db as _db
        from datetime import datetime

        cfg = config_bridge.get_scan_config()
        threshold = cfg.get('deletion_threshold', 3)

        all_items = _db.get_all_persistent_for_check()
        if not all_items:
            logger.info("[Detection] 持久化结果集为空，跳过检测")
            self._last_cycle_at = _db.now_str()
            self._last_cycle_result = {'total': 0, 'ok': 0, 'failed': 0, 'deleted': 0}
            return

        logger.info(f"[Detection] 开始检测 {len(all_items)} 条记录...")
        start_time = datetime.now()
        ok_count = 0
        fail_count = 0

        sem = asyncio.Semaphore(30)
        timeout = aiohttp.ClientTimeout(total=5)
        async with get_session(limit=30, timeout=timeout) as session:
            async def check_one(item):
                nonlocal ok_count, fail_count
                url = item['url']
                if not url.startswith(('http://', 'https://')):
                    _db.update_persistent_check(url, ok=False)
                    fail_count += 1
                    return

                async with sem:
                    alive = await _quick_check(session, url)
                    if alive:
                        # 连接成功，保持已有指标不变
                        _db.update_persistent_check(url, ok=True)
                        ok_count += 1
                    else:
                        _db.update_persistent_check(url, ok=False)
                        fail_count += 1

            await asyncio.gather(*[check_one(item) for item in all_items])

        # 删除达到阈值的记录
        deleted = _db.delete_persistent_by_threshold(threshold)

        elapsed = (datetime.now() - start_time).total_seconds()
        self._last_cycle_at = _db.now_str()
        self._last_cycle_result = {
            'total': len(all_items),
            'ok': ok_count,
            'failed': fail_count,
            'deleted': deleted,
            'elapsed_seconds': round(elapsed, 1),
        }
        logger.info(
            f"[Detection] 检测完成: 总计={len(all_items)}, "
            f"通过={ok_count}, 失败={fail_count}, 删除={deleted}, "
            f"耗时={elapsed:.1f}s"
        )


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


# 全局单例
detection_manager = DetectionManager()

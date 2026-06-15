# -*- coding: utf-8 -*-
"""
定期检测模块。
在后台定期检测 persistent_scan_results 中的所有源，
连续失败达到阈值的自动删除。
"""
import asyncio
import logging
import uuid

import aiohttp

from . import config_bridge
from .network import get_session
from .video_check import deep_check

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

    def _log(self, level, message):
        """写入 Python logger 同时持久化到数据库。"""
        if level == 'ERROR':
            logger.error(message)
        elif level == 'WARNING':
            logger.warning(message)
        else:
            logger.info(message)
        try:
            import database as _db
            _db.insert_detection_log(level, message)
        except Exception:
            pass

    async def _loop(self):
        """主循环：等待间隔 → 执行检测 → 循环。"""
        while self._running:
            cfg = config_bridge.get_scan_config()
            interval = cfg.get('detection_interval_minutes', 120)
            if interval <= 0:
                await asyncio.sleep(60)
                continue

            self._log('INFO', f"[Detection] 下次检测将在 {interval} 分钟后")
            await asyncio.sleep(interval * 60)

            if not self._running:
                break
            await self._run_detection_cycle(trigger_source='auto')

    async def _run_detection_cycle(self, trigger_source='auto'):
        """执行一次完整的检测周期，结果持久化到数据库。"""
        import database as _db
        from datetime import datetime

        cfg = config_bridge.get_scan_config()
        threshold = cfg.get('deletion_threshold', 3)

        all_items = _db.get_all_persistent_for_check()
        if not all_items:
            self._log('INFO', "[Detection] 持久化结果集为空，跳过检测")
            self._last_cycle_at = _db.now_str()
            self._last_cycle_result = {'total': 0, 'ok': 0, 'failed': 0, 'deleted': 0}
            return

        # 创建本轮检测记录
        now = datetime.now()
        started_at = _db.now_str()
        cycle_id = f"det_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        _db.insert_detection_run(cycle_id, started_at, trigger_source)

        self._log('INFO', f"[Detection] 开始检测 {len(all_items)} 条记录 (cycle={cycle_id})...")
        start_time = now
        ok_count = 0
        fail_count = 0
        results_list = []

        sem = asyncio.Semaphore(10)
        async with get_session(limit=10, timeout=6) as session:
            async def check_one(item):
                nonlocal ok_count, fail_count
                async with sem:  # 统一限流：含非 http 分支，避免一次性铺开数千协程同步写 DB
                    url = item['url']
                    name = item.get('name', '')

                    if not url.startswith(('http://', 'https://')):
                        _db.update_persistent_check(url, ok=False)
                        fail_count += 1
                        results_list.append({
                            'url': url, 'name': name, 'check_ok': False,
                            'http_status': 0, 'response_time_ms': 0,
                            'response_size_bytes': 0, 'consecutive_failures': 0,
                            'quality_status': 'unreachable',
                        })
                        return

                    perf = await deep_check(session, url)
                    if perf is not None:
                        _db.update_persistent_check(
                            url, ok=True,
                            stability=perf['stability'],
                            delay=perf['delay'],
                            bandwidth=perf['bandwidth'],
                        )
                        ok_count += 1
                        psr = _db.get_persistent_by_url(url)
                        results_list.append({
                            'url': url, 'name': name, 'check_ok': True,
                            'http_status': 200,
                            'response_time_ms': perf['delay'],
                            'response_size_bytes': 0,
                            'consecutive_failures': 0,
                            'quality_status': psr['quality_status'] if psr else 'good',
                        })
                    else:
                        _db.update_persistent_check(url, ok=False)
                        fail_count += 1
                        psr = _db.get_persistent_by_url(url)
                        results_list.append({
                            'url': url, 'name': name, 'check_ok': False,
                            'http_status': 0, 'response_time_ms': 0,
                            'response_size_bytes': 0,
                            'consecutive_failures': psr['consecutive_failures'] if psr else 0,
                            'quality_status': psr['quality_status'] if psr else 'unreachable',
                        })

            await asyncio.gather(*[check_one(item) for item in all_items])

        # 删除达到阈值的记录
        deleted = _db.delete_persistent_by_threshold(threshold)

        elapsed = (datetime.now() - start_time).total_seconds()
        finished_at = _db.now_str()
        self._last_cycle_at = finished_at
        self._last_cycle_result = {
            'total': len(all_items),
            'ok': ok_count,
            'failed': fail_count,
            'deleted': deleted,
            'elapsed_seconds': round(elapsed, 1),
        }

        # 持久化本轮结果
        _db.insert_detection_results(cycle_id, results_list)
        _db.finish_detection_run(
            cycle_id, finished_at,
            len(all_items), ok_count, fail_count, deleted,
            round(elapsed, 1),
        )
        _db.cleanup_old_detection_runs(keep=20)
        # 兜底清理过期的测速日志
        try:
            _db.cleanup_old_run_logs(days=30)
        except Exception:
            pass

        self._log(
            'INFO',
            f"[Detection] 检测完成: 总计={len(all_items)}, "
            f"通过={ok_count}, 失败={fail_count}, 删除={deleted}, "
            f"耗时={elapsed:.1f}s"
        )
        try:
            _db.flush_log_buffer()
        except Exception:
            pass
        try:
            _db.clear_detection_logs()
        except Exception:
            pass


async def _quick_check(session, url):
    """快速检查 URL，返回详细结果字典。"""
    result = {'alive': False, 'status': 0, 'time_ms': 0, 'bytes': 0}
    try:
        from datetime import datetime
        start = datetime.now()
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=4),
                               allow_redirects=True) as r:
            result['status'] = r.status
            if r.status != 200:
                result['time_ms'] = (datetime.now() - start).total_seconds() * 1000
                return result
            total = 0
            async for chunk in r.content.iter_chunked(2048):
                total += len(chunk)
                if total >= 4096:
                    result['alive'] = True
                    result['bytes'] = total
                    result['time_ms'] = (datetime.now() - start).total_seconds() * 1000
                    return result
            result['alive'] = total > 0
            result['bytes'] = total
            result['time_ms'] = (datetime.now() - start).total_seconds() * 1000
            return result
    except Exception:
        return result


# 全局单例
detection_manager = DetectionManager()

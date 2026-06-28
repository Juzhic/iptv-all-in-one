# -*- coding: utf-8 -*-
"""
定期检测模块。
在后台定期检测 persistent_scan_results 中的所有源，
连续失败达到阈值的自动软删除，并定期尝试复活已删除的条目。
"""
import asyncio
import logging
import random
import threading
import uuid
from collections import defaultdict
from datetime import timedelta
from urllib.parse import urlparse

from . import config_bridge
from .network import get_session, quick_http_check
from .video_check import run_deep_check

logger = logging.getLogger('scanner.detection')


def _local_now():
    from datetime import datetime
    try:
        from database import LOCAL_TZ
        return datetime.now(LOCAL_TZ).replace(tzinfo=None)
    except Exception:
        return datetime.now()


def _format_local_dt(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.strftime('%Y-%m-%d %H:%M:%S')


class DetectionManager:
    """定期检测管理器，运行在 AsyncBridge 的事件循环上。"""

    def __init__(self):
        self._task = None
        self._running = False
        self._reload_event = threading.Event()
        self._last_cycle_at = None
        self._last_cycle_result = None
        self._last_resurrection_at = None
        self._next_cycle_at = None
        self._cycle_running = False

    @property
    def status(self):
        """返回检测模块当前状态。"""
        return {
            'running': self._running,
            'cycle_running': self._cycle_running,
            'last_cycle_at': _format_local_dt(self._last_cycle_at),
            'last_cycle_result': self._last_cycle_result,
            'last_resurrection_at': _format_local_dt(self._last_resurrection_at),
            'next_cycle_at': self._next_cycle_at,
        }

    def _broadcast_status(self):
        try:
            from . import broadcast_detection_sse
            broadcast_detection_sse('status', self.status)
        except Exception:
            pass

    def _set_next_cycle_at(self, value):
        next_cycle_at = _format_local_dt(value)
        if self._next_cycle_at == next_cycle_at:
            return
        self._next_cycle_at = next_cycle_at
        self._broadcast_status()

    def start(self):
        """启动检测循环。"""
        if self._task and not self._task.done():
            logger.info("[Detection] 检测循环已在运行")
            return
        from . import bridge
        self._running = True
        self._task = bridge.run_background(self._loop())
        self._broadcast_status()
        logger.info("[Detection] 检测循环已启动")

    def stop(self):
        """停止检测循环。"""
        self._running = False
        self._reload_event.set()
        self._set_next_cycle_at(None)
        self._broadcast_status()
        if self._task and not self._task.done():
            self._task.cancel()
            logger.info("[Detection] 检测循环已停止")

    def reload_config(self):
        """唤醒检测循环，尽快重新读取配置。"""
        self._reload_event.set()

    async def _sleep_or_reload(self, seconds):
        deadline = asyncio.get_running_loop().time() + max(0, seconds)
        while self._running:
            if self._reload_event.is_set():
                self._reload_event.clear()
                return True
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return False
            await asyncio.sleep(min(remaining, 5))
        return False

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
        try:
            ts = _local_now().strftime('%H:%M:%S')
            from . import broadcast_detection_sse
            broadcast_detection_sse('log', {'ts': ts, 'level': level, 'message': message})
        except Exception:
            pass

    async def _loop(self):
        """主循环：等待间隔 → 执行检测 → 复活检查 → 循环。"""
        while self._running:
            cfg = config_bridge.get_scan_config()
            interval = cfg.get('detection_interval_minutes', 120)
            if interval <= 0:
                self._set_next_cycle_at(None)
                await self._sleep_or_reload(60)
                continue

            self._set_next_cycle_at(_local_now() + timedelta(minutes=interval))

            self._log('INFO', f"[Detection] 下次检测将在 {interval} 分钟后")
            if await self._sleep_or_reload(interval * 60):
                continue

            if not self._running:
                break
            self._set_next_cycle_at(None)
            await self._run_detection_cycle(trigger_source='auto')

            # 检查是否需要执行复活检测
            if cfg.get('resurrection_enabled', True):
                resurrection_interval_hours = cfg.get('resurrection_interval_hours', 24)
                should_run = False
                if self._last_resurrection_at is None:
                    should_run = True
                else:
                    elapsed = _local_now() - self._last_resurrection_at
                    if elapsed >= timedelta(hours=resurrection_interval_hours):
                        should_run = True
                if should_run:
                    await self._run_resurrection_check()

    async def _run_detection_cycle(self, trigger_source='auto'):
        """执行一次完整的检测周期，结果持久化到数据库。"""
        cfg = config_bridge.get_scan_config()
        timeout_minutes = cfg.get('detection_cycle_timeout_minutes', 30)
        self._cycle_running = True
        self._broadcast_status()
        try:
            await asyncio.wait_for(
                self._run_detection_cycle_inner(cfg, trigger_source),
                timeout=timeout_minutes * 60,
            )
        except asyncio.TimeoutError:
            self._log('WARNING', f"[Detection] 检测周期超时 ({timeout_minutes} 分钟)，已中止")
            if not self._last_cycle_result or not self._last_cycle_result.get('error'):
                self._last_cycle_at = None
        except Exception as exc:
            self._log(
                'ERROR',
                f"[Detection] 检测周期异常中止: {type(exc).__name__}: {exc}"
            )
            self._last_cycle_at = None
            self._last_cycle_result = {
                'total': 0,
                'ok': 0,
                'failed': 0,
                'skipped': 0,
                'deleted': 0,
                'error': f"{type(exc).__name__}: {exc}",
            }
        finally:
            self._cycle_running = False
            self._broadcast_status()

    async def _run_detection_cycle_inner(self, cfg, trigger_source='auto'):
        """执行一次完整的检测周期（内部实现）。"""
        import database as _db
        threshold = cfg.get('deletion_threshold', 3)

        # 使用分层检测：稳定频道降低检测频率
        try:
            all_items = _db.get_persistent_for_check_tiered()
        except Exception:
            all_items = _db.get_all_persistent_for_check()
        if not all_items:
            self._log('INFO', "[Detection] 持久化结果集为空，跳过检测")
            self._last_cycle_at = _db.now_str()
            self._last_cycle_result = {'total': 0, 'ok': 0, 'failed': 0, 'skipped': 0, 'deleted': 0}
            return

        # 创建本轮检测记录
        now = _local_now()
        started_at = _db.now_str()
        cycle_id = f"det_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        _db.insert_detection_run(cycle_id, started_at, trigger_source)

        self._log('INFO', f"[Detection] 开始检测 {len(all_items)} 条记录 (cycle={cycle_id})...")
        start_time = now
        ok_count = 0
        fail_count = 0
        skipped_count = 0
        results_list = []
        updates_to_apply = []
        finalized = False

        def finish_cycle(total_checked, deleted, elapsed, error=None):
            nonlocal finalized
            if finalized:
                return _db.now_str(), error

            finished_at = _db.now_str()
            final_error = error
            if results_list:
                try:
                    _db.insert_detection_results(cycle_id, results_list)
                except Exception as exc:
                    detail_error = f"检测明细写入失败: {type(exc).__name__}: {exc}"
                    logger.exception("[Detection] %s (cycle=%s)", detail_error, cycle_id)
                    final_error = f"{final_error}; {detail_error}" if final_error else detail_error

            _db.finish_detection_run(
                cycle_id, finished_at,
                total_checked, ok_count, fail_count, deleted,
                round(elapsed, 1), final_error,
            )
            finalized = True
            return finished_at, final_error

        try:
            # Pre-fetch consecutive_failures for local tracking
            all_urls = [item['url'] for item in all_items]
            try:
                cf_cache = _db.get_consecutive_failures_batch(all_urls)
            except Exception:
                cf_cache = {}

            # 按 source_ip (URL host) 分组，实现熔断机制
            groups = defaultdict(list)
            for item in all_items:
                try:
                    host = urlparse(item['url']).hostname or item['url']
                except Exception:
                    host = item['url']
                groups[host].append(item)

            sem = asyncio.Semaphore(10)
            async with get_session(limit=10, timeout=6) as session:
                async def check_one(item):
                    nonlocal ok_count, fail_count
                    async with sem:
                        url = item['url']
                        name = item.get('name', '')

                        if not url.startswith(('http://', 'https://')):
                            updates_to_apply.append({'url': url, 'ok': False, 'name': name})
                            cf_cache[url] = cf_cache.get(url, 0) + 1
                            fail_count += 1
                            results_list.append({
                                'url': url, 'name': name, 'check_ok': False,
                                'http_status': 0, 'response_time_ms': 0,
                                'response_size_bytes': 0,
                                'consecutive_failures': cf_cache.get(url, 0),
                                'quality_status': 'unreachable',
                            })
                            return False

                        try:
                            perf = await run_deep_check(session, url)
                            if perf is None:
                                await asyncio.sleep(2)
                                perf = await run_deep_check(session, url)
                        except Exception as exc:
                            perf = None
                            self._log(
                                'WARNING',
                                f"[Detection] 单项检测异常: {name} ({url}) - "
                                f"{type(exc).__name__}: {exc}"
                            )

                        if perf is not None:
                            updates_to_apply.append({
                                'url': url, 'ok': True, 'name': name,
                                'stability': perf['stability'],
                                'delay': perf['delay'],
                                'bandwidth': perf['bandwidth'],
                                'jitter': perf.get('jitter'),
                            })
                            ok_count += 1
                            quality_status = _db._evaluate_quality(
                                perf['stability'], perf['delay'], perf['bandwidth']
                            )
                            results_list.append({
                                'url': url, 'name': name, 'check_ok': True,
                                'http_status': 200,
                                'response_time_ms': perf['delay'],
                                'response_size_bytes': 0,
                                'consecutive_failures': 0,
                                'quality_status': quality_status,
                            })
                            return True
                        else:
                            updates_to_apply.append({'url': url, 'ok': False, 'name': name})
                            cf_cache[url] = cf_cache.get(url, 0) + 1
                            fail_count += 1
                            results_list.append({
                                'url': url, 'name': name, 'check_ok': False,
                                'http_status': 0, 'response_time_ms': 0,
                                'response_size_bytes': 0,
                                'consecutive_failures': cf_cache.get(url, 0),
                                'quality_status': 'unreachable',
                            })
                            return False

                async def check_group(host, items):
                    nonlocal skipped_count
                    sample_size = min(5, len(items))
                    if sample_size < 5:
                        for item in items:
                            await check_one(item)
                        return
                    sample = random.sample(items, sample_size) if len(items) > sample_size else items
                    rest = [item for item in items if item not in sample]

                    sample_results = await asyncio.gather(*[check_one(item) for item in sample])
                    all_sample_failed = all(not ok for ok in sample_results)

                    if all_sample_failed and rest:
                        skipped_count += len(rest)
                        for item in rest:
                            url = item['url']
                            name = item.get('name', '')
                            updates_to_apply.append({'url': url, 'ok': False, 'name': name})
                            cf_cache[url] = cf_cache.get(url, 0) + 1
                            results_list.append({
                                'url': url, 'name': name, 'check_ok': False,
                                'http_status': 0, 'response_time_ms': 0,
                                'response_size_bytes': 0,
                                'consecutive_failures': cf_cache.get(url, 0),
                                'quality_status': 'circuit_breaker_skipped',
                            })
                            self._log(
                                'WARNING',
                                f"[Detection] 熔断跳过: {name} ({url})"
                            )
                    else:
                        for item in rest:
                            await check_one(item)

                await asyncio.gather(*[check_group(host, items) for host, items in groups.items()])

            # 批量更新所有检测结果
            _db.batch_update_persistent_checks(updates_to_apply)

            # 删除达到阈值的记录
            deleted = _db.delete_persistent_by_threshold(threshold)

            elapsed = (_local_now() - start_time).total_seconds()
            finished_at, final_error = finish_cycle(
                len(all_items), deleted, elapsed
            )
            self._last_cycle_at = finished_at
            self._last_cycle_result = {
                'total': len(all_items),
                'ok': ok_count,
                'failed': fail_count,
                'skipped': skipped_count,
                'deleted': deleted,
                'elapsed_seconds': round(elapsed, 1),
            }
            if final_error:
                self._last_cycle_result['error'] = final_error

            _db.cleanup_old_detection_runs(keep=20)
            try:
                keep_days = cfg.get('quality_history_keep_days', 90)
                _db.cleanup_quality_history(keep_days=keep_days)
            except Exception:
                pass
            # 兜底清理过期的测速日志
            try:
                from database.db import RUN_LOGS_RETENTION_DAYS
                _db.cleanup_old_run_logs(days=RUN_LOGS_RETENTION_DAYS)
            except Exception:
                pass

            self._log(
                'INFO',
                f"[Detection] 检测完成: 总计={len(all_items)}, "
                f"通过={ok_count}, 失败={fail_count}, 熔断跳过={skipped_count}, "
                f"删除={deleted}, 耗时={elapsed:.1f}s"
            )
            try:
                _db.flush_log_buffer()
            except Exception:
                pass
            try:
                _db.clear_detection_logs()
            except Exception:
                pass
        except asyncio.CancelledError:
            elapsed = (_local_now() - start_time).total_seconds()
            error = "检测被取消或超时"
            finished_at, final_error = finish_cycle(
                len(results_list), 0, elapsed, error=error
            )
            self._last_cycle_at = finished_at
            self._last_cycle_result = {
                'total': len(results_list),
                'ok': ok_count,
                'failed': fail_count,
                'skipped': skipped_count,
                'deleted': 0,
                'elapsed_seconds': round(elapsed, 1),
                'error': final_error or error,
            }
            raise
        except Exception as exc:
            elapsed = (_local_now() - start_time).total_seconds()
            error = f"{type(exc).__name__}: {exc}"
            finished_at, final_error = finish_cycle(
                len(results_list), 0, elapsed, error=error
            )
            self._last_cycle_at = finished_at
            self._last_cycle_result = {
                'total': len(results_list),
                'ok': ok_count,
                'failed': fail_count,
                'skipped': skipped_count,
                'deleted': 0,
                'elapsed_seconds': round(elapsed, 1),
                'error': final_error or error,
            }
            raise

    async def _run_resurrection_check(self):
        """检查已软删除的条目，尝试复活仍可访问的源。"""
        import database as _db

        cfg = config_bridge.get_scan_config()
        if not cfg.get('resurrection_enabled', True):
            return

        deleted_items = _db.get_deleted_persistent_for_resurrection(limit=100)
        if not deleted_items:
            self._log('INFO', "[Resurrection] 无软删除条目需要检查")
            self._last_resurrection_at = _local_now()
            return

        self._log('INFO', f"[Resurrection] 开始检查 {len(deleted_items)} 条软删除记录...")
        resurrected = 0
        checked = 0

        sem = asyncio.Semaphore(10)
        async with get_session(limit=10, timeout=6) as session:
            async def check_one(item):
                nonlocal resurrected, checked
                async with sem:
                    url = item['url']
                    name = item.get('name', '')
                    checked += 1

                    if not url.startswith(('http://', 'https://')):
                        return

                    result = await quick_http_check(session, url)
                    if result['alive']:
                        perf = await run_deep_check(session, url)
                        if perf is not None:
                            _db.restore_persistent(url)
                            _db.update_persistent_check(
                                url, ok=True,
                                stability=perf['stability'],
                                delay=perf['delay'],
                                bandwidth=perf['bandwidth'],
                                jitter=perf.get('jitter'),
                            )
                            resurrected += 1
                            self._log(
                                'INFO',
                                f"[Resurrection] 复活成功: {name} ({url}) "
                                f"[stability={perf['stability']}, delay={perf['delay']}ms, "
                                f"bandwidth={perf['bandwidth']}]"
                            )
                        else:
                            _db.restore_persistent(url)
                            _db.update_persistent_check(url, ok=False)
                            self._log(
                                'INFO',
                                f"[Resurrection] 复活但质量检测失败: {name} ({url}) "
                                f"[status={result['status']}, {result['time_ms']:.0f}ms]"
                            )

            await asyncio.gather(*[check_one(item) for item in deleted_items])

        self._last_resurrection_at = _local_now()
        self._log(
            'INFO',
            f"[Resurrection] 检查完成: 检查={checked}, 复活={resurrected}"
        )
        try:
            _db.flush_log_buffer()
        except Exception:
            pass





# 全局单例
detection_manager = DetectionManager()

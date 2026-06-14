# -*- coding: utf-8 -*-
"""
scanner_integration 包入口。
提供异步扫描到同步 Flask 路由的桥接层。
"""
import asyncio
import threading
import time
import uuid
from datetime import datetime

from .logger_bridge import logger
from . import config_bridge


# ==================== 扫描日志 ====================

_scan_log_seq = 0


def _init_log_seq():
    """从数据库恢复日志序号（防止服务重启后序号冲突）。"""
    global _scan_log_seq
    try:
        import database as _db
        conn = _db._get_conn()
        row = conn.execute("SELECT MAX(seq) as max_seq FROM scan_logs").fetchone()
        if row and row['max_seq']:
            _scan_log_seq = row['max_seq']
    except Exception:
        pass


def _scan_log(msg):
    """记录一条扫描日志，写入数据库，前端可增量拉取。"""
    global _scan_log_seq
    _scan_log_seq += 1
    time_str = datetime.now().strftime('%H:%M:%S')
    try:
        import database as _db
        _db.insert_scan_log(_scan_log_seq, time_str, msg)
    except Exception:
        pass  # DB 写入失败不影响扫描流程
    logger.info(msg)


_init_log_seq()


# ==================== 扫描状态管理 ====================

class ScanState:
    """管理扫描运行时的可变状态，替代 state.py 的全局变量。"""

    def __init__(self):
        self.lock = asyncio.Lock()
        self.channels = []        # 当前有效频道列表
        self.failure_counts = {}  # url -> 连续失败次数
        self.last_update_time = None
        self.initialized = False
        self._stop_requested = False

    def request_stop(self):
        self._stop_requested = True

    def clear_stop(self):
        self._stop_requested = False

    @property
    def stop_requested(self):
        return self._stop_requested


# ==================== 异步桥接 ====================

class AsyncBridge:
    """在守护线程中维护一个 asyncio 事件循环。"""

    def __init__(self):
        self._loop = None
        self._thread = None
        self._start_lock = threading.Lock()

    def start(self):
        with self._start_lock:
            if self._loop is not None and self._loop.is_running():
                return
            if self._loop is not None and self._thread is not None and self._thread.is_alive():
                # 线程已启动但循环还没标记 running，等一下
                for _ in range(50):
                    if self._loop.is_running():
                        return
                    time.sleep(0.05)
                return
            self._loop = asyncio.new_event_loop()
            self._thread = threading.Thread(target=self._run, daemon=True, name='scan-async')
            self._thread.start()
        logger.info("[Bridge] 异步事件循环已启动")

    def _run(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def run_sync(self, coro, timeout=None):
        """将协程提交到异步循环并阻塞等待结果。"""
        if self._loop is None or not self._loop.is_running():
            raise RuntimeError("异步事件循环未启动，请先调用 bridge.start()")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    def run_background(self, coro):
        """在异步循环中启动后台协程，不等待结果。"""
        if self._loop is None or not self._loop.is_running():
            raise RuntimeError("异步事件循环未启动")
        asyncio.run_coroutine_threadsafe(coro, self._loop)


# 全局实例
bridge = AsyncBridge()
scan_state = ScanState()


def init_bridge():
    """初始化桥接层，启动异步事件循环、加载别名、初始化 KeyManager、启动定时扫描。"""
    bridge.start()
    # 通过共享 alias.py 模块加载别名
    try:
        import engine.alias as _alias
        _alias.load_aliases()
        logger.info("[Bridge] 别名已从数据库加载")
    except Exception as e:
        logger.warning(f"[Bridge] 加载别名失败: {e}")
    # 初始化多 Key 管理器
    try:
        from .key_manager import init_key_manager
        init_key_manager()
    except Exception as e:
        logger.warning(f"[Bridge] KeyManager 初始化失败: {e}")
    # 启动定时扫描任务
    start_daily_task()
    # 启动每日数据库维护任务
    start_daily_db_maintenance()
    # 启动定期检测任务
    try:
        from .detection import detection_manager
        detection_manager.start()
    except Exception as e:
        logger.warning(f"[Bridge] 检测模块启动失败: {e}")


# ==================== 扫描编排协程 ====================

async def _do_scan(platforms_override=None, provinces_override=None):
    """执行完整的扫描流程：采集 → 快速过滤 → 深度检测 → 保存数据库。"""
    from .platforms import collect_all, deduplicate
    from .video_check import fast_filter, background_deep_update
    from .channel_utils import resolve_name
    import database as _db

    cfg = config_bridge.get_scan_config()
    scan_id = f"scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    started_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    scan_state.clear_stop()
    # 清空上次日志
    global _scan_log_seq
    _scan_log_seq = 0
    try:
        _db.clear_scan_logs()
    except Exception:
        pass

    # 覆盖配置（仅在内存中修改，不回写数据库，避免覆盖用户 API Key）
    if platforms_override is not None:
        cfg['enabled_platforms'] = platforms_override
    if provinces_override is not None:
        cfg['selected_provinces'] = provinces_override

    # 写入扫描记录
    _db.insert_scan_run({
        'scan_id': scan_id,
        'started_at': started_at,
        'status': 'running',
        'platforms_used': str(cfg.get('enabled_platforms', [])),
    })
    _db.update_scan_progress(
        running=True, started_at=started_at, phase='collecting',
        total=0, processed=0, percent=0, message='正在采集频道...'
    )

    try:
        # 阶段1：采集
        _scan_log(f"[Scan:{scan_id}] 开始采集...")
        raw, actual_platforms = await collect_all(log_fn=_scan_log)
        # 用实际启用的平台覆盖 platforms_used
        if actual_platforms:
            _db.update_scan_run(scan_id, platforms_used=str(actual_platforms))
        if scan_state.stop_requested:
            _db.update_scan_run(scan_id, status='stopped', finished_at=_db.now_str())
            _db.clear_scan_progress()
            return scan_id

        if not raw:
            _scan_log(f"[Scan:{scan_id}] 采集完成，未获取到任何频道。请检查 API Key 是否已配置。")
            _db.update_scan_run(scan_id, status='completed', finished_at=_db.now_str(),
                                total_raw=0)
            _db.update_scan_progress(running=False, phase='idle', message='采集完成，未获取到频道',
                                     percent=100)
            scan_state.initialized = True
            return scan_id

        # 去重
        uniq = deduplicate(raw)
        for ch in uniq:
            if not ch.get('province'):
                ch['province'] = '未知'
            if not ch.get('city'):
                ch['city'] = ''

        _scan_log(f"[Scan:{scan_id}] 采集到 {len(raw)} 条，去重后 {len(uniq)} 条")
        _db.update_scan_run(scan_id, total_raw=len(raw), total_deduped=len(uniq))
        _db.update_scan_progress(phase='fast_filter', total=len(uniq),
                                 message=f'快速过滤 {len(uniq)} 个频道...')

        # 阶段2：快速过滤
        _scan_log(f"[Scan:{scan_id}] 开始快速过滤 {len(uniq)} 个频道...")
        quick = await fast_filter(uniq, log_fn=_scan_log)
        if scan_state.stop_requested:
            _db.update_scan_run(scan_id, status='stopped', finished_at=_db.now_str())
            _db.clear_scan_progress()
            return scan_id

        # 补充分类
        for ch in quick:
            if 'category' not in ch or not ch['category']:
                name_cat = resolve_name(ch.get('name', ''))
                ch['category'] = name_cat[1] if isinstance(name_cat, tuple) else ''

        _db.update_scan_run(scan_id, total_fast_pass=len(quick))

        # 批量写入数据库
        _db.insert_scan_results(scan_id, quick)
        _scan_log(f"[Scan:{scan_id}] 快速过滤完成，{len(quick)} 个频道存活")

        # 更新扫描状态
        scan_state.channels = quick
        scan_state.failure_counts = {c['url']: 0 for c in quick}
        scan_state.last_update_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        scan_state.initialized = True

        # 阶段3：后台深度检测
        _db.update_scan_progress(phase='deep_check', total=len(quick), processed=0,
                                 percent=0, message=f'深度检测 {len(quick)} 个频道...')

        _scan_log(f"[Scan:{scan_id}] 启动后台深度检测...")
        await background_deep_update(quick, log_fn=_scan_log)

        # 从 video_check 模块级状态读取深度检测结果
        from . import video_check as _vc
        sorted_channels = list(_vc.QUICK_CHANNELS)

        # 将检测指标写回数据库
        for ch in sorted_channels:
            if ch.get('stability', 0) > 0:
                _db.update_scan_result_stability(
                    scan_id, ch['url'], ch['stability'],
                    delay=ch.get('delay'), bandwidth=ch.get('bandwidth'),
                    resolution=ch.get('resolution'), codec=ch.get('codec')
                )

        # 更新最终结果
        if sorted_channels:
            scan_state.channels = sorted_channels
            _db.update_scan_run(scan_id, total_deep_pass=len([
                c for c in sorted_channels if c.get('stability', 0) >= 30
            ]))

        duration = (datetime.now() - datetime.strptime(started_at, '%Y-%m-%d %H:%M:%S')).total_seconds()
        _db.update_scan_run(scan_id, status='completed', finished_at=_db.now_str(),
                            duration_seconds=round(duration, 1))
        _db.update_scan_progress(running=False, phase='idle', percent=100,
                                 message=f'扫描完成，{len(quick)} 个频道')
        _scan_log(f"[Scan:{scan_id}] 扫描完成，耗时 {duration:.1f}s，共 {len(quick)} 个频道")

        # 合并到持久化结果集
        try:
            from .persistence import merge_scan_to_persistent
            await merge_scan_to_persistent(scan_id)
            _scan_log(f"[Scan:{scan_id}] 已合并到持久化结果集")
        except Exception as e:
            _scan_log(f"[Scan:{scan_id}] 合并到持久化结果集失败: {e}")
            logger.warning(f"[Scan:{scan_id}] 合并到持久化结果集失败: {e}")

    except BaseException as e:
        _scan_log(f"[Scan:{scan_id}] 扫描异常: {e}")
        try:
            _db.update_scan_run(scan_id, status='failed', finished_at=_db.now_str(), error=str(e))
        except Exception:
            pass
        _db.update_scan_progress(running=False, phase='idle', message=f'扫描失败: {e}')

    # 刷新日志缓冲区
    try:
        _db.flush_log_buffer()
    except Exception:
        pass

    return scan_id


# NOTE: 以下函数为死代码——web.py 中没有路由调用 trigger_health_check()。
# 实际的健康检测由 detection.py 的 DetectionManager 负责。
# 保留供将来可能的独立健康检查 UI 功能使用。
async def _do_health_check():
    """执行健康检查。"""
    from .video_check import health_check
    from . import video_check as _vc
    import database as _db

    # 确保 video_check 的模块级状态与 scan_state 同步
    if scan_state.channels:
        _vc.QUICK_CHANNELS = list(scan_state.channels)
        _vc.failure_count = dict(scan_state.failure_counts)

    if not _vc.QUICK_CHANNELS:
        _scan_log("[Health] 无频道可检查，请先执行一次扫描")
        return

    _db.update_scan_progress(running=True, phase='health_check',
                             total=len(_vc.QUICK_CHANNELS), processed=0,
                             message='正在执行健康检查...')
    _scan_log(f"[Health] 开始健康检查，{len(_vc.QUICK_CHANNELS)} 个频道")

    try:
        await health_check()

        # 从 video_check 模块级状态读回结果
        scan_state.channels = list(_vc.QUICK_CHANNELS)
        scan_state.failure_counts = dict(_vc.failure_count)
        scan_state.last_update_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        _db.update_scan_progress(running=False, phase='idle', percent=100,
                                 message=f'健康检查完成，{len(_vc.QUICK_CHANNELS)} 个频道存活')
        _scan_log(f"[Health] 健康检查完成，{len(_vc.QUICK_CHANNELS)} 个频道存活")
    except BaseException as e:
        logger.exception(f"[Health] 健康检查异常: {e}")
        _db.update_scan_progress(running=False, phase='idle', message=f'健康检查失败: {e}')


# ==================== 同步入口函数（供 Flask 路由调用） ====================

def trigger_scan(platforms=None, provinces=None):
    """启动扫描（后台执行，立即返回）。"""
    progress = db_get_scan_progress()
    if progress and progress.get('running'):
        return {'error': '扫描正在进行中'}

    def _run():
        try:
            bridge.run_sync(_do_scan(platforms, provinces))
        except BaseException as e:
            _scan_log(f"[Trigger] 扫描执行异常: {e}")
        finally:
            # 无论成功失败，确保进度状态不卡在 running
            import database as _db
            _db.clear_scan_progress()

    _scan_log("[Trigger] 正在启动扫描...")
    t = threading.Thread(target=_run, daemon=True, name='scan-trigger')
    t.start()
    return {'ok': True, 'status': 'started'}


def trigger_stop():
    """请求停止扫描。如果扫描已死则直接清除状态。"""
    import database as _db
    progress = _db.get_scan_progress()
    if progress and progress.get('running'):
        scan_state.request_stop()
        # 同时直接清除 running 状态，防止卡死
        _db.clear_scan_progress()
    else:
        _db.clear_scan_progress()
    return {'ok': True, 'message': '已请求停止'}


def force_clear_scan():
    """强制清除扫描状态（用于恢复卡死的扫描）。"""
    import database as _db
    scan_state.request_stop()
    _db.clear_scan_progress()
    return {'ok': True, 'message': '扫描状态已清除'}


# NOTE: 死代码——web.py 中没有路由调用此函数，见 _do_health_check 注释。
def trigger_health_check():
    """启动健康检查（后台执行）。"""
    progress = db_get_scan_progress()
    if progress and progress.get('running'):
        return {'error': '扫描正在进行中'}

    def _run():
        try:
            bridge.run_sync(_do_health_check())
        except BaseException as e:
            _scan_log(f"[Health] 健康检查异常: {e}")
        finally:
            import database as _db
            _db.clear_scan_progress()

    _scan_log("[Health] 正在启动健康检查...")
    t = threading.Thread(target=_run, daemon=True, name='health-check')
    t.start()
    return {'ok': True, 'status': 'started'}


def get_scan_status():
    """获取扫描进度，附带增量日志行（从数据库读取，关闭浏览器再回来也能看到）。"""
    import database as _db
    progress = db_get_scan_progress()
    latest_run = _db.get_latest_scan_run() or {}

    progress['summary'] = {
        'scan_id': latest_run.get('scan_id', ''),
        'status': latest_run.get('status', ''),
        'started_at': latest_run.get('started_at', ''),
        'finished_at': latest_run.get('finished_at', ''),
        'duration_seconds': latest_run.get('duration_seconds', 0) or 0,
        'total_raw': latest_run.get('total_raw', 0) or 0,
        'total_deduped': latest_run.get('total_deduped', 0) or 0,
        'total_fast_pass': latest_run.get('total_fast_pass', 0) or 0,
        'total_deep_pass': latest_run.get('total_deep_pass', 0) or 0,
    }

    if progress.get('phase') == 'deep_check':
        try:
            from . import video_check as _vc
            deep_progress = getattr(_vc, 'update_progress', {}) or {}
            percent = int(deep_progress.get('percent') or progress.get('percent') or 0)
            total = int(progress.get('total') or 0)
            progress['percent'] = max(0, min(100, percent))
            if total > 0 and percent > 0:
                progress['processed'] = min(total, max(int(progress.get('processed') or 0), round(total * percent / 100)))
            if deep_progress.get('message'):
                progress['message'] = deep_progress['message']
        except Exception:
            pass

    # 始终附上日志行，前端通过 last_log_seq 增量消费
    progress['lines'] = _db.get_scan_logs(after_seq=0, limit=300)
    progress['last_log_seq'] = _scan_log_seq
    return progress


def get_scan_results(scan_id=None, page=1, size=50, category=None,
                     province=None, search=None):
    """分页查询扫描结果。"""
    import database as _db
    return _db.get_scan_results(scan_id=scan_id, page=page, size=size,
                                category=category, province=province, search=search)


def get_latest_scan():
    """获取最新扫描记录。"""
    import database as _db
    return _db.get_latest_scan_run()


def get_scan_history(limit=50):
    """获取扫描历史。"""
    import database as _db
    return _db.get_scan_history(limit=limit)


def delete_scan(scan_id):
    """删除扫描记录。"""
    import database as _db
    _db.delete_scan_run(scan_id)
    return {'status': 'deleted'}


def get_scan_stats(scan_id=None):
    """获取扫描结果统计。"""
    import database as _db
    return _db.get_scan_stats(scan_id=scan_id)


def get_scan_config():
    """获取扫描配置。"""
    return config_bridge.get_scan_config()


def save_scan_config(cfg):
    """保存扫描配置。"""
    config_bridge.save_scan_config(cfg)
    return {'status': 'saved'}


# ==================== 持久化结果桥接函数 ====================

def get_persistent_grouped():
    """获取持久化结果的两级分组汇总。"""
    import database as _db
    return _db.get_persistent_grouped()


def get_persistent_details(source_ip):
    """获取某个来源 IP 的频道明细。"""
    import database as _db
    return _db.get_persistent_details_by_ip(source_ip)


def get_persistent_stats():
    """获取持久化结果的质量统计。"""
    import database as _db
    return _db.get_persistent_stats()


def get_all_persistent_for_detection_table():
    """获取所有持久化结果用于检测概览表格。"""
    import database as _db
    return _db.get_all_persistent_for_detection_table()


def get_detection_runs(start=None, end=None, limit=100):
    """获取检测轮次记录。"""
    import database as _db
    return _db.get_detection_runs(start, end, limit)


def get_detection_results(cycle_id):
    """获取某轮检测的 URL 结果明细。"""
    import database as _db
    return _db.get_detection_results(cycle_id)


def trigger_persistent_manual_check():
    """手动触发一轮持久化结果检测。"""
    from .detection import detection_manager
    if bridge._loop is None:
        return {'ok': False, 'error': '异步循环未启动'}
    asyncio.run_coroutine_threadsafe(
        detection_manager._run_detection_cycle(trigger_source='manual'), bridge._loop
    )
    return {'ok': True, 'status': 'started'}


def delete_persistent_item(row_id):
    """删除单条持久化结果。"""
    import database as _db
    _db.delete_persistent_by_id(row_id)
    return {'status': 'deleted'}


def get_detection_status():
    """获取检测模块状态。"""
    from .detection import detection_manager
    return detection_manager.status


def db_get_scan_progress():
    """读取扫描进度。"""
    import database as _db
    return _db.get_scan_progress()


# ==================== 定时扫描任务 ====================

def start_daily_task():
    """在异步事件循环中启动定时扫描任务。"""
    if bridge._loop is None:
        logger.warning("[Scheduler] 异步循环未启动，无法启动定时任务")
        return
    asyncio.run_coroutine_threadsafe(_daily_update_task(), bridge._loop)
    logger.info("[Scheduler] 定时扫描任务已启动")


async def _daily_update_task():
    """定时扫描后台协程：按配置的星期几和时间自动触发扫描。"""
    from datetime import datetime as _dt, timedelta as _td

    while True:
        try:
            cfg = config_bridge.get_scan_config()
            update_time = cfg.get('update_time', '03:00')
            update_days = cfg.get('update_days', [0, 1, 2, 3, 4, 5, 6])
            daily_full = cfg.get('daily_full_update', True)

            if daily_full:
                update_days = [0, 1, 2, 3, 4, 5, 6]

            # 解析时间
            try:
                hour, minute = map(int, update_time.split(':'))
            except (ValueError, AttributeError):
                hour, minute = 3, 0

            # 查找下一个匹配时间（最多遍历未来 8 天）
            now = _dt.now()
            target = None
            for day_offset in range(8):
                candidate = (now + _td(days=day_offset)).replace(
                    hour=hour, minute=minute, second=0, microsecond=0
                )
                # weekday(): 0=Mon, 6=Sun — 与 update_days 编号一致
                if candidate.weekday() in update_days and candidate > now:
                    target = candidate
                    break

            if target is None:
                logger.warning("[Scheduler] 未找到匹配的扫描时间，60 秒后重试")
                await asyncio.sleep(60)
                continue

            wait_seconds = (target - now).total_seconds()
            logger.info(f"[Scheduler] 下次扫描: {target.strftime('%Y-%m-%d %H:%M')} "
                        f"(等待 {wait_seconds:.0f} 秒)")
            await asyncio.sleep(wait_seconds)

            # 到达目标时间，检查是否有正在进行的扫描
            import database as _db
            progress = _db.get_scan_progress()
            if progress and progress.get('running'):
                logger.info("[Scheduler] 已有扫描在运行，跳过本次")
                await asyncio.sleep(60)
                continue

            # 触发扫描
            logger.info("[Scheduler] 定时扫描触发")
            await _do_scan()

            # 防止重复触发
            await asyncio.sleep(60)

        except asyncio.CancelledError:
            logger.info("[Scheduler] 定时任务被取消")
            break
        except Exception as e:
            logger.exception(f"[Scheduler] 定时任务异常: {e}")
            await asyncio.sleep(60)


# ==================== 每日数据库维护 ====================

def start_daily_db_maintenance():
    """在异步事件循环中启动每日数据库维护任务（每天凌晨 4 点）。"""
    if bridge._loop is None:
        logger.warning("[DBMaint] 异步循环未启动，无法启动维护任务")
        return
    asyncio.run_coroutine_threadsafe(_daily_db_maintenance_task(), bridge._loop)
    logger.info("[DBMaint] 每日数据库维护任务已启动")


async def _daily_db_maintenance_task():
    """每天凌晨执行：清理过期日志 + VACUUM 压缩数据库。"""
    from datetime import datetime as _dt, timedelta as _td

    MAINT_HOUR, MAINT_MINUTE = 4, 0  # 凌晨 4:00 执行

    while True:
        try:
            now = _dt.now()
            target = now.replace(hour=MAINT_HOUR, minute=MAINT_MINUTE, second=0, microsecond=0)
            if target <= now:
                target += _td(days=1)
            wait_seconds = (target - now).total_seconds()
            logger.info(f"[DBMaint] 下次维护: {target.strftime('%Y-%m-%d %H:%M')} "
                        f"(等待 {wait_seconds:.0f} 秒)")
            await asyncio.sleep(wait_seconds)

            import database as _db
            logger.info("[DBMaint] 开始每日数据库维护...")

            # 1. 清理过期日志
            try:
                deleted = _db.cleanup_old_run_logs(days=30)
                logger.info(f"[DBMaint] 清理过期 run_logs: {deleted} 条")
            except Exception as e:
                logger.warning(f"[DBMaint] 清理 run_logs 失败: {e}")

            # 2. VACUUM 压缩数据库（扫描运行时跳过，防止并发写入损坏数据库）
            try:
                import os
                progress = _db.get_scan_progress()
                if progress.get('running'):
                    logger.info("[DBMaint] 扫描正在进行中，跳过 VACUUM 以避免并发写入风险")
                else:
                    size_before = os.path.getsize(_db.DB_PATH)
                    _db.vacuum_database()
                    size_after = os.path.getsize(_db.DB_PATH)
                    saved_mb = (size_before - size_after) / (1024 * 1024)
                    logger.info(f"[DBMaint] VACUUM 完成: {size_before / 1024 / 1024:.1f}MB → "
                                f"{size_after / 1024 / 1024:.1f}MB (释放 {saved_mb:.1f}MB)")
            except Exception as e:
                logger.warning(f"[DBMaint] VACUUM 失败: {e}")

            logger.info("[DBMaint] 每日维护完成")
            # 防止同一天重复触发
            await asyncio.sleep(60)

        except asyncio.CancelledError:
            logger.info("[DBMaint] 维护任务被取消")
            break
        except Exception as e:
            logger.exception(f"[DBMaint] 维护任务异常: {e}")
            await asyncio.sleep(60)

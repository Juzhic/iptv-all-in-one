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
        import db as _db
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
        import db as _db
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

    def start(self):
        if self._loop is not None and self._loop.is_running():
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
        import alias as _alias
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


# ==================== 扫描编排协程 ====================

async def _do_scan(platforms_override=None, provinces_override=None):
    """执行完整的扫描流程：采集 → 快速过滤 → 深度检测 → 保存数据库。"""
    from .platforms import collect_all, deduplicate
    from .video_check import fast_filter, background_deep_update
    from .channel_utils import resolve_name
    import db as _db

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
        raw = await collect_all()
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
        quick = await fast_filter(uniq)
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
        await background_deep_update(quick)

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

    except BaseException as e:
        _scan_log(f"[Scan:{scan_id}] 扫描异常: {e}")
        try:
            _db.update_scan_run(scan_id, status='failed', finished_at=_db.now_str(), error=str(e))
        except Exception:
            pass
        _db.update_scan_progress(running=False, phase='idle', message=f'扫描失败: {e}')

    return scan_id


async def _do_health_check():
    """执行健康检查。"""
    from .video_check import health_check
    from . import video_check as _vc
    import db as _db

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
            import db as _db
            _db.clear_scan_progress()

    _scan_log("[Trigger] 正在启动扫描...")
    t = threading.Thread(target=_run, daemon=True, name='scan-trigger')
    t.start()
    return {'ok': True, 'status': 'started'}


def trigger_stop():
    """请求停止扫描。如果扫描已死则直接清除状态。"""
    import db as _db
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
    import db as _db
    scan_state.request_stop()
    _db.clear_scan_progress()
    return {'ok': True, 'message': '扫描状态已清除'}


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
            import db as _db
            _db.clear_scan_progress()

    _scan_log("[Health] 正在启动健康检查...")
    t = threading.Thread(target=_run, daemon=True, name='health-check')
    t.start()
    return {'ok': True, 'status': 'started'}


def get_scan_status():
    """获取扫描进度，附带增量日志行（从数据库读取，关闭浏览器再回来也能看到）。"""
    import db as _db
    progress = db_get_scan_progress()
    # 始终附上日志行，前端通过 last_log_seq 增量消费
    progress['lines'] = _db.get_scan_logs(after_seq=0, limit=300)
    progress['last_log_seq'] = _scan_log_seq
    return progress


def get_scan_results(scan_id=None, page=1, size=50, category=None,
                     province=None, search=None):
    """分页查询扫描结果。"""
    import db as _db
    return _db.get_scan_results(scan_id=scan_id, page=page, size=size,
                                category=category, province=province, search=search)


def get_latest_scan():
    """获取最新扫描记录。"""
    import db as _db
    return _db.get_latest_scan_run()


def get_scan_history(limit=50):
    """获取扫描历史。"""
    import db as _db
    return _db.get_scan_history(limit=limit)


def delete_scan(scan_id):
    """删除扫描记录。"""
    import db as _db
    _db.delete_scan_run(scan_id)
    return {'status': 'deleted'}


def get_scan_stats(scan_id=None):
    """获取扫描结果统计。"""
    import db as _db
    return _db.get_scan_stats(scan_id=scan_id)


def get_scan_config():
    """获取扫描配置。"""
    return config_bridge.get_scan_config()


def save_scan_config(cfg):
    """保存扫描配置。"""
    config_bridge.save_scan_config(cfg)
    return {'status': 'saved'}


def feed_scan_to_test(scan_id, channel_names=None):
    """将扫描结果送入 IPTV-Test 测速流水线。返回 test_list 格式。"""
    import db as _db

    results = _db.get_scan_results_for_feed(scan_id, channel_names)
    if not results:
        return None, '没有可测速的频道'

    # 转换为 IPTV-Test 内部格式: [(channel_info_dict, url), ...]
    test_list = []
    for r in results:
        channel_info = {'name': r['name']}
        test_list.append((channel_info, r['url']))

    # 按频道去重，每个频道保留所有 URL
    seen_urls = set()
    deduped = []
    for info, url in test_list:
        if url not in seen_urls:
            seen_urls.add(url)
            deduped.append((info, url))

    return deduped, None


def db_get_scan_progress():
    """读取扫描进度。"""
    import db as _db
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
            import db as _db
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

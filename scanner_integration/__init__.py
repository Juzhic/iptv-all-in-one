# -*- coding: utf-8 -*-
"""
scanner_integration 包入口，提供异步扫描到同步 Flask 路由的桥接层。"""
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
    """记录一条扫描日志，写入数据库，前端可增量拉取"""
    global _scan_log_seq
    _scan_log_seq += 1
    time_str = datetime.now().strftime('%H:%M:%S')
    try:
        import database as _db
        _db.insert_scan_log(_scan_log_seq, time_str, msg)
    except Exception:
        pass  # DB 写入失败不影响扫描流程。
    logger.info(msg)
    # 广播给 SSE 订阅者
    try:
        _broadcast_sse('log', {'seq': _scan_log_seq, 'time': time_str, 'msg': msg})
    except Exception:
        pass


_init_log_seq()


# ==================== 扫描状态管理====================

# SSE 订阅者列表（线程安全）
import queue
import threading as _threading

_sse_subscribers: list[queue.Queue] = []
_sse_lock = _threading.Lock()


def subscribe_sse():
    """注册一个 SSE 订阅者，返回 Queue。"""
    q = queue.Queue(maxsize=500)
    with _sse_lock:
        _sse_subscribers.append(q)
    return q


def unsubscribe_sse(q):
    """取消 SSE 订阅。"""
    with _sse_lock:
        try:
            _sse_subscribers.remove(q)
        except ValueError:
            pass


def _broadcast_sse(event_type, data):
    """向所有 SSE 订阅者广播事件（非阻塞，丢弃满队列）。"""
    import json as _json
    msg = f"event: {event_type}\ndata: {_json.dumps(data, ensure_ascii=False)}\n\n"
    with _sse_lock:
        dead = []
        for q in _sse_subscribers:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _sse_subscribers.remove(q)


# ==================== 检测日志 SSE ====================

_detection_sse_subscribers: list[queue.Queue] = []
_detection_sse_lock = _threading.Lock()


def subscribe_detection_sse():
    """注册一个检测 SSE 订阅者，返回 Queue。"""
    q = queue.Queue(maxsize=500)
    with _detection_sse_lock:
        _detection_sse_subscribers.append(q)
    return q


def unsubscribe_detection_sse(q):
    """取消检测 SSE 订阅。"""
    with _detection_sse_lock:
        try:
            _detection_sse_subscribers.remove(q)
        except ValueError:
            pass


def broadcast_detection_sse(event_type, data):
    """向所有检测 SSE 订阅者广播事件（非阻塞，丢弃满队列）。"""
    import json as _json
    msg = f"event: {event_type}\ndata: {_json.dumps(data, ensure_ascii=False)}\n\n"
    with _detection_sse_lock:
        dead = []
        for q in _detection_sse_subscribers:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _detection_sse_subscribers.remove(q)


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
        logger.info("[Bridge] 异步事件循环已启动。")

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
            raise RuntimeError("异步事件循环未启动。")
        asyncio.run_coroutine_threadsafe(coro, self._loop)


# 全局实例
bridge = AsyncBridge()
scan_state = ScanState()


def _restore_from_persistent():
    """从持久化结果集恢复频道到内存状态（缓存恢复机制）。"""
    import database as _db
    try:
        rows = _db.get_all_persistent_for_check()
        if not rows:
            logger.info("[Bridge] 持久化结果集为空，等待首次扫描。")
            return
        # 仅恢复有效的（非软删除）条目，映射为 scan_state 兼容格式
        channels = []
        for r in rows:
            channels.append({
                'url': r['url'],
                'name': r['name'],
                'stability': r.get('stability', 0) or 0,
                'delay': r.get('delay'),
                'bandwidth': r.get('bandwidth'),
            })
        scan_state.channels = channels
        scan_state.initialized = True
        scan_state.last_update_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        logger.info(f"[Bridge] 从持久化结果集恢复 {len(channels)} 个频道，切换到增量模式。")
    except Exception as e:
        logger.warning(f"[Bridge] 从持久化结果集恢复失败: {e}")


def init_bridge():
    """初始化桥接层，启动异步事件循环、加载别名、初始化 KeyManager、启动定时扫描。"""
    bridge.start()
    # 通过共享 alias.py 模块加载别名
    try:
        import engine.alias as _alias
        _alias.load_aliases()
        logger.info("[Bridge] 别名已从数据库加载。")
    except Exception as e:
        logger.warning(f"[Bridge] 加载别名失败: {e}")
    # 初始化多 Key 管理器
    try:
        from .key_manager import init_key_manager
        init_key_manager()
    except Exception as e:
        logger.warning(f"[Bridge] KeyManager 初始化失败: {e}")
    # 从持久化结果集恢复频道缓存
    _restore_from_persistent()
    # 启动定时扫描任务
    start_daily_task()
    # 启动每日数据库维护任务
    start_daily_db_maintenance()
    # 启动定期检测任务
    try:
        from .detection import detection_manager
        detection_manager.start()
    except Exception as e:
        logger.warning(f"[Bridge] 检测模块启动失败。 {e}")


# ==================== 扫描编排协程 ====================


def _deduplicate_and_normalize(raw):
    """去重并标准化频道数据。"""
    from .platforms import deduplicate
    uniq = deduplicate(raw)
    for ch in uniq:
        if not ch.get('province'):
            ch['province'] = '未知'
        if not ch.get('city'):
            ch['city'] = ''
    return uniq


async def _do_scan(platforms_override=None, provinces_override=None):
    """执行完整的扫描流程：采集 -> 快速过滤 -> 深度检测 -> 保存数据库。"""
    from .platforms import collect_all
    from .video_check import fast_filter, background_deep_update
    from .channel_utils import resolve_name
    from .network import get_session
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
    _broadcast_sse('progress', {'phase': 'collecting', 'percent': 0, 'message': '正在采集频道...'})

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
            _db.update_scan_progress(running=False, phase='idle', message='采集完成，未获取到频道。',
                                     percent=100)
            scan_state.initialized = True
            return scan_id

        # 去重
        uniq = _deduplicate_and_normalize(raw)

        _scan_log(f"[Scan:{scan_id}] 采集到 {len(raw)} 条，去重后 {len(uniq)} 条。")
        _db.update_scan_run(scan_id, total_raw=len(raw), total_deduped=len(uniq))

        # ISP Intelligence：分析历史数据中的热点段并主动扫描
        if cfg.get('isp_intelligence_enabled'):
            try:
                from .isp_intelligence import scan_hot_segments
                _scan_log(f"[Scan:{scan_id}] ISP Intelligence: 正在分析热点段...")
                async with get_session(limit=30, force_close=True) as isp_session:
                    isp_channels = await scan_hot_segments(isp_session)
                if isp_channels:
                    _scan_log(f"[Scan:{scan_id}] ISP Intelligence: 发现 {len(isp_channels)} 个频道，正在合并...")
                    raw.extend(isp_channels)
                    uniq = _deduplicate_and_normalize(raw)
                    _db.update_scan_run(scan_id, total_raw=len(raw), total_deduped=len(uniq))
                    _scan_log(f"[Scan:{scan_id}] ISP Intelligence 合并完成，去重后 {len(uniq)} 条。")
                else:
                    _scan_log(f"[Scan:{scan_id}] ISP Intelligence: 未发现新频道")
            except Exception as e:
                _scan_log(f"[Scan:{scan_id}] ISP Intelligence 异常: {e}")
                logger.warning(f"[Scan:{scan_id}] ISP Intelligence 异常: {e}")

        # 社区源扫描：从 GitHub 公开 M3U 仓库采集频道
        if cfg.get('community_sources_enabled'):
            try:
                from .community_sources import scan_community_sources
                _scan_log(f"[Scan:{scan_id}] 社区源：正在采集公开 M3U 列表...")
                async with get_session(limit=30, force_close=True) as cs_session:
                    cs_channels = await scan_community_sources(session=cs_session)
                if cs_channels:
                    _scan_log(f"[Scan:{scan_id}] 社区源：发现 {len(cs_channels)} 个频道，正在合并...")
                    raw.extend(cs_channels)
                    uniq = _deduplicate_and_normalize(raw)
                    _db.update_scan_run(scan_id, total_raw=len(raw), total_deduped=len(uniq))
                    _scan_log(f"[Scan:{scan_id}] 社区源合并完成，去重后 {len(uniq)} 条。")
                else:
                    _scan_log(f"[Scan:{scan_id}] 社区源：未发现新频道")
            except Exception as e:
                _scan_log(f"[Scan:{scan_id}] 社区源扫描异常: {e}")
                logger.warning(f"[Scan:{scan_id}] 社区源扫描异常: {e}")

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
        _scan_log(f"[Scan:{scan_id}] 快速过滤完成，{len(quick)} 个频道存储。")

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
                                 message=f'扫描完成，{len(quick)} 个频道。')
        _scan_log(f"[Scan:{scan_id}] 扫描完成，耗时 {duration:.1f}s，共 {len(quick)} 个频道。")

        # 合并到持久化结果集
        try:
            from .persistence import merge_scan_to_persistent
            await merge_scan_to_persistent(scan_id)
            _scan_log(f"[Scan:{scan_id}] 已合并到持久化结果集")
        except Exception as e:
            _scan_log(f"[Scan:{scan_id}] 合并到持久化结果集失败: {type(e).__name__}: {e}")
            logger.warning(f"[Scan:{scan_id}] 合并到持久化结果集失败: {type(e).__name__}: {e}")

    except Exception as e:
        _scan_log(f"[Scan:{scan_id}] 扫描异常: {e}")
        try:
            _db.update_scan_run(scan_id, status='failed', finished_at=_db.now_str(), error=str(e))
        except Exception:
            pass
        _db.update_scan_progress(running=False, phase='idle', message=f'扫描失败: {e}')
        _broadcast_sse('scan_complete', {'ok': False, 'error': str(e)})

    # 刷新日志缓冲区
    try:
        _db.flush_log_buffer()
    except Exception:
        pass

    return scan_id


async def _do_incremental_scan(platforms_override=None, provinces_override=None):
    """增量扫描：先检查现有频道，再采集新源，仅对新 URL 做快速过滤和深度检测。"""
    from .platforms import collect_all
    from .video_check import fast_filter, background_deep_update, health_check_persistent
    from .channel_utils import resolve_name
    from .network import get_session
    import database as _db

    cfg = config_bridge.get_scan_config()
    scan_id = f"scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    started_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    scan_state.clear_stop()
    global _scan_log_seq
    _scan_log_seq = 0
    try:
        _db.clear_scan_logs()
    except Exception:
        pass

    if platforms_override is not None:
        cfg['enabled_platforms'] = platforms_override
    if provinces_override is not None:
        cfg['selected_provinces'] = provinces_override

    _db.insert_scan_run({
        'scan_id': scan_id,
        'started_at': started_at,
        'status': 'running',
        'platforms_used': str(cfg.get('enabled_platforms', [])),
    })
    _db.update_scan_progress(
        running=True, started_at=started_at, phase='health_check',
        total=0, processed=0, percent=0, message='正在检查现有频道...'
    )

    try:
        # 阶段1：健康检查现有持久化频道
        _scan_log(f"[Incremental:{scan_id}] 增量模式启动，先检查现有频道...")
        existing_urls = set()
        try:
            existing = _db.get_all_persistent_for_check()
            existing_urls = {r['url'] for r in existing}
            if existing:
                _scan_log(f"[Incremental:{scan_id}] 现有 {len(existing_urls)} 个频道，开始健康检查...")
                await health_check_persistent(existing, log_fn=_scan_log)
        except Exception as e:
            _scan_log(f"[Incremental:{scan_id}] 健康检查异常（继续扫描）: {e}")

        # 阶段2：采集新源
        _scan_log(f"[Incremental:{scan_id}] 开始采集新源...")
        raw, actual_platforms = await collect_all(log_fn=_scan_log)
        if actual_platforms:
            _db.update_scan_run(scan_id, platforms_used=str(actual_platforms))
        if scan_state.stop_requested:
            _db.update_scan_run(scan_id, status='stopped', finished_at=_db.now_str())
            _db.clear_scan_progress()
            return scan_id

        if not raw:
            _scan_log(f"[Incremental:{scan_id}] 采集完成，未发现新频道。")
            _db.update_scan_run(scan_id, status='completed', finished_at=_db.now_str(), total_raw=0)
            _db.update_scan_progress(running=False, phase='idle', percent=100, message='增量扫描完成，无新频道。')
            return scan_id

        uniq = _deduplicate_and_normalize(raw)

        # 过滤掉已知 URL，仅保留新发现的
        new_channels = [ch for ch in uniq if ch['url'] not in existing_urls]
        _scan_log(f"[Incremental:{scan_id}] 采集到 {len(raw)} 条，去重后 {len(uniq)} 条，新频道 {len(new_channels)} 条。")
        _db.update_scan_run(scan_id, total_raw=len(raw), total_deduped=len(uniq))

        if not new_channels:
            _scan_log(f"[Incremental:{scan_id}] 无新频道，跳过过滤。")
            _db.update_scan_run(scan_id, status='completed', finished_at=_db.now_str())
            _db.update_scan_progress(running=False, phase='idle', percent=100, message='增量扫描完成，无新频道。')
            return scan_id

        # 阶段3：仅对新频道做快速过滤
        _db.update_scan_progress(phase='fast_filter', total=len(new_channels),
                                 message=f'快速过滤 {len(new_channels)} 个新频道...')
        _scan_log(f"[Incremental:{scan_id}] 快速过滤 {len(new_channels)} 个新频道...")
        quick = await fast_filter(new_channels, log_fn=_scan_log)
        if scan_state.stop_requested:
            _db.update_scan_run(scan_id, status='stopped', finished_at=_db.now_str())
            _db.clear_scan_progress()
            return scan_id

        for ch in quick:
            if 'category' not in ch or not ch['category']:
                name_cat = resolve_name(ch.get('name', ''))
                ch['category'] = name_cat[1] if isinstance(name_cat, tuple) else ''

        _db.update_scan_run(scan_id, total_fast_pass=len(quick))
        _db.insert_scan_results(scan_id, quick)
        _scan_log(f"[Incremental:{scan_id}] 新频道快速过滤完成，{len(quick)} 个通过。")

        # 阶段4：仅对新频道做深度检测
        if quick:
            _db.update_scan_progress(phase='deep_check', total=len(quick), processed=0,
                                     percent=0, message=f'深度检测 {len(quick)} 个新频道...')
            _scan_log(f"[Incremental:{scan_id}] 深度检测 {len(quick)} 个新频道...")
            await background_deep_update(quick, log_fn=_scan_log)

            from . import video_check as _vc
            sorted_channels = list(_vc.QUICK_CHANNELS)
            for ch in sorted_channels:
                if ch.get('stability', 0) > 0:
                    _db.update_scan_result_stability(
                        scan_id, ch['url'], ch['stability'],
                        delay=ch.get('delay'), bandwidth=ch.get('bandwidth'),
                        resolution=ch.get('resolution'), codec=ch.get('codec')
                    )

        duration = (datetime.now() - datetime.strptime(started_at, '%Y-%m-%d %H:%M:%S')).total_seconds()
        _db.update_scan_run(scan_id, status='completed', finished_at=_db.now_str(),
                            duration_seconds=round(duration, 1))
        _db.update_scan_progress(running=False, phase='idle', percent=100,
                                 message=f'增量扫描完成，新频道 {len(quick)} 个。')
        _scan_log(f"[Incremental:{scan_id}] 增量扫描完成，耗时 {duration:.1f}s，新频道 {len(quick)} 个。")

        # 合并到持久化结果集
        try:
            from .persistence import merge_scan_to_persistent
            await merge_scan_to_persistent(scan_id)
            _scan_log(f"[Incremental:{scan_id}] 已合并到持久化结果集")
        except Exception as e:
            _scan_log(f"[Incremental:{scan_id}] 合并到持久化结果集失败: {type(e).__name__}: {e}")

        # 更新内存状态
        scan_state.last_update_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    except Exception as e:
        _scan_log(f"[Incremental:{scan_id}] 增量扫描异常: {e}")
        try:
            _db.update_scan_run(scan_id, status='failed', finished_at=_db.now_str(), error=str(e))
        except Exception:
            pass
        _db.update_scan_progress(running=False, phase='idle', message=f'增量扫描失败: {e}')

    try:
        _db.flush_log_buffer()
    except Exception:
        pass

    return scan_id


def trigger_scan(platforms=None, provinces=None):
    """触发全量扫描（入口，供路由调用）。"""
    import database as _db
    progress = _db.get_scan_progress()
    if progress and progress.get('running'):
        return {'ok': False, 'error': '扫描正在进行中'}
    bridge.start()  # 确保异步循环已启动
    bridge.run_background(_do_scan(
        platforms_override=platforms,
        provinces_override=provinces,
    ))
    return {'ok': True, 'mode': 'full'}


def trigger_stop():
    """请求停止扫描。"""
    scan_state.request_stop()
    return {'ok': True, 'message': '已请求停止扫描'}


def force_clear_scan():
    """强制清除卡死的扫描状态。"""
    import database as _db
    # 清除数据库中的扫描进度
    _db.clear_scan_progress()
    # 重置内存状态
    scan_state.clear_stop()
    return {'ok': True, 'message': '扫描状态已清除'}


def trigger_incremental_scan(platforms_override=None, provinces_override=None):
    """触发增量扫描（入口，供路由或定时任务调用）。"""
    import database as _db
    progress = _db.get_scan_progress()
    if progress and progress.get('running'):
        return {'ok': False, 'error': '扫描正在进行中'}
    bridge.run_background(_do_incremental_scan(
        platforms_override=platforms_override,
        provinces_override=provinces_override,
    ))
    return {'ok': True, 'mode': 'incremental'}


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


# ==================== 持久化结果桥接函数。====================

def get_persistent_grouped():
    """获取持久化结果的两级分组汇总。"""
    import database as _db
    return _db.get_persistent_grouped()


def get_persistent_details(source_ip, page=None, size=50):
    """获取某个来源 IP 的频道明细。"""
    import database as _db
    return _db.get_persistent_details_by_ip(source_ip, page=page, size=size)


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


def get_detection_results(cycle_id, page=None, size=100):
    """获取某轮检测的 URL 结果明细。"""
    import database as _db
    return _db.get_detection_results(cycle_id, page=page, size=size)


def trigger_persistent_manual_check():
    """手动触发一轮持久化结果检测。"""
    from .detection import detection_manager
    if bridge._loop is None:
        return {'ok': False, 'error': '异步循环未启动。'}
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
    logger.info("[Scheduler] 定时扫描任务已启动。")


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
                # weekday(): 0=Mon, 6=Sun 与 update_days 编号一致
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
            logger.info("[Scheduler] 定时任务被取消。")
            break
        except Exception as e:
            logger.exception(f"[Scheduler] 定时任务异常: {e}")
            await asyncio.sleep(60)


# ==================== 每日数据库维护。====================

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
                from database.db import RUN_LOGS_RETENTION_DAYS
                deleted = _db.cleanup_old_run_logs(days=RUN_LOGS_RETENTION_DAYS)
                logger.info(f"[DBMaint] 清理过期 run_logs: {deleted} 条。")
            except Exception as e:
                logger.warning(f"[DBMaint] 清理 run_logs 失败: {e}")

            # 2. 数据库维护（MySQL 无需 VACUUM）
            try:
                progress = _db.get_scan_progress()
                if progress.get('running'):
                    logger.info("[DBMaint] 扫描正在进行中，跳过维护。")
                else:
                    _db.vacuum_database()  # MySQL 下为空操作
                    logger.info("[DBMaint] 数据库维护完成（MySQL 无需 VACUUM）")
            except Exception as e:
                logger.warning(f"[DBMaint] 维护异常: {e}")

            logger.info("[DBMaint] 每日维护完成")
            # 防止同一天重复触发
            await asyncio.sleep(60)

        except asyncio.CancelledError:
            logger.info("[DBMaint] 维护任务被取消。")
            break
        except Exception as e:
            logger.exception(f"[DBMaint] 维护任务异常: {e}")
            await asyncio.sleep(60)

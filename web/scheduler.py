# -*- coding: utf-8 -*-
"""web 包 — 定时调度器管理。

提取自 web.py 的调度器锁、循环和状态管理。
"""
import os
import time
import threading
from datetime import datetime

from engine import load_config
from database import now_str, get_scheduler_state, update_scheduler_state, clear_scheduler_state

import web.state as _state


def _format_schedule_time(value):
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%d %H:%M:%S')
    return value or None


def _write_scheduler_state(running, next_run=None):
    try:
        update_scheduler_state(
            running=running,
            next_run=_format_schedule_time(next_run),
            owner=_state._scheduler_owner if running else '',
        )
    except Exception:
        pass


def _acquire_scheduler_lock():
    """跨进程抢占调度器锁，避免 gunicorn/uWSGI 多 worker 重复定时执行。"""
    if _state._scheduler_lock_handle is not None:
        return True

    os.makedirs('output', exist_ok=True)
    lock_handle = open(os.path.join('output', 'scheduler.lock'), 'a+', encoding='utf-8')
    try:
        if os.name == 'nt':
            import msvcrt
            lock_handle.seek(0)
            msvcrt.locking(lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock_handle.close()
        return False

    lock_handle.seek(0)
    lock_handle.truncate()
    lock_handle.write(f'{_state._scheduler_owner} {now_str()}\n')
    lock_handle.flush()
    _state.set_scheduler_lock_handle(lock_handle)
    return True


def _release_scheduler_lock():
    handle = _state._scheduler_lock_handle
    if handle is None:
        return
    try:
        if os.name == 'nt':
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        handle.close()
    finally:
        _state.set_scheduler_lock_handle(None)


def _ensure_scheduler_started(cfg=None):
    """在当前配置需要定时时启动调度线程；WSGI 导入模式也会生效。"""
    try:
        cfg = cfg or load_config()
    except Exception:
        return False

    if cfg.get('run_mode', 'once') == 'once':
        return False

    with _state._scheduler_thread_lock:
        if _state._scheduler_thread is not None and _state._scheduler_thread.is_alive():
            return True
        if not _acquire_scheduler_lock():
            return False
        _state.set_scheduler_running(True)
        _write_scheduler_state(True, _state._next_scheduled_run)
        t = threading.Thread(target=_scheduler_loop, daemon=True, name='scheduler')
        _state.set_scheduler_thread(t)
        t.start()
        return True


def _scheduler_status():
    """返回页面展示用的调度状态，兼容多进程请求落到非调度 worker。"""
    if not _state._scheduler_running:
        _ensure_scheduler_started()

    next_run_str = _format_schedule_time(_state._next_scheduled_run)
    scheduler_running = _state._scheduler_running
    if next_run_str and scheduler_running:
        return scheduler_running, next_run_str

    try:
        state = get_scheduler_state()
    except Exception:
        state = None
    if state and state.get('running'):
        return True, state.get('next_run') or next_run_str
    return scheduler_running, next_run_str


def _scheduler_loop():
    """后台调度循环：按配置的 run_mode 定时触发测试。"""
    _state.set_scheduler_running(True)
    _write_scheduler_state(True, _state._next_scheduled_run)
    from engine.test_engine import _next_run_datetime
    from web.test_runner import _start_test_background, _is_run_token_active

    try:
        while True:
            cfg = load_config()
            run_mode = cfg.get('run_mode', 'once')
            if run_mode == 'once':
                _state.set_next_scheduled_run(None)
                _write_scheduler_state(False, None)
                break

            next_run = _next_run_datetime(run_mode, cfg.get('run_times', []), cfg.get('run_interval_minutes', 0))
            if next_run is None:
                _state.set_next_scheduled_run(None)
                _write_scheduler_state(True, None)
                time.sleep(60)
                continue

            _state.set_next_scheduled_run(next_run)
            _write_scheduler_state(True, next_run)
            wait_sec = (next_run - datetime.now()).total_seconds()
            if wait_sec > 0:
                while wait_sec > 0:
                    time.sleep(min(wait_sec, 30))
                    wait_sec = (next_run - datetime.now()).total_seconds()
                    current_cfg = load_config()
                    current_mode = current_cfg.get('run_mode', 'once')
                    if current_mode != run_mode:
                        break
                else:
                    pass

                current_cfg = load_config()
                if current_cfg.get('run_mode', 'once') != run_mode:
                    continue

            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"{'#' * 60}")
            logger.info(f"定时任务触发：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info(f"{'#' * 60}")
            run_token = _start_test_background(trigger_source='scheduler')
            if run_token is None:
                logger.warning("已有测试正在运行，本次定时任务跳过，等待下一个设定时间点")
                continue

            if run_mode == 'interval':
                while _is_run_token_active(run_token):
                    time.sleep(5)
                continue
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"调度器异常退出: {e}")
    finally:
        _state.set_scheduler_running(False)
        _state.set_next_scheduled_run(None)
        _state.set_scheduler_thread(None)
        try:
            clear_scheduler_state()
        except Exception:
            pass
        _release_scheduler_lock()


def _start_scheduler_from_config():
    """模块导入时也按配置启动调度器，兼容 WSGI/宝塔部署。"""
    try:
        cfg = load_config()
    except Exception:
        return
    if cfg.get('run_mode', 'once') != 'once':
        _ensure_scheduler_started(cfg)

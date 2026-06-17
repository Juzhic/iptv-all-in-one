# -*- coding: utf-8 -*-
"""web 包 — 后台测试运行器。

提取自 web.py 的 _is_run_token_active / _start_test_background。
"""
import threading
import time
from datetime import datetime

from database import now_str
import web.state as _state


# ─────────────── 触发测试 API ───────────────

def _is_run_token_active(run_token):
    """判断指定后台任务是否仍是当前活跃任务。"""
    with _state._test_lock:
        return _state._test_running and _state._test_active_token is run_token


def _start_test_background(trigger_source='web', test_list=None, scan_id=None):
    """启动一次后台测试。返回本次任务 token；已有测试在运行时返回 None。"""
    with _state._test_lock:
        if _state._test_running:
            return None
        run_token = object()
        stop_event = threading.Event()
        _state.set_test_running(True)
        _state.set_test_stop_event(stop_event)
        _state.set_test_active_token(run_token)

    # 重置进度
    _state._test_progress.update({
        'running': True,
        'started_at': now_str(),
        'total': 0, 'processed': 0, 'passed': 0, 'failed': 0,
        'elapsed': 0, 'finished_at': None, 'error': None,
        'source': trigger_source,
        'last_seq': 0,
    })
    _state._test_log_lines.clear()
    _state.reset_test_log_seq()
    _start_time = time.time()
    _run_id = now_str().replace('-', '').replace(':', '').replace(' ', '_')

    def _on_progress(info):
        _state._test_progress.update({
            'total': info.get('total', 0),
            'processed': info.get('processed', 0),
            'passed': info.get('success', 0),
            'failed': info.get('failed', 0),
            'elapsed': round(time.time() - _start_time, 1),
            'last_seq': _state._test_log_seq,
        })

    def _on_log(msg):
        seq = _state.inc_test_log_seq()
        now = datetime.now().strftime('%H:%M:%S')
        _state._test_log_lines.append({
            'seq': seq,
            'time': now,
            'msg': msg,
        })

    def _run():
        try:
            from engine.test_engine import run_test_cycle
            run_test_cycle(
                progress_callback=_on_progress,
                log_callback=_on_log,
                stop_event=stop_event,
                progress_source=trigger_source,
                test_list=test_list,
                scan_id=scan_id,
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"测试失败: {e}")
            _on_log(f"测试异常终止: {e}")
            _state._test_progress['error'] = str(e)
        finally:
            with _state._test_lock:
                is_current_run = _state._test_active_token is run_token
            if is_current_run:
                _on_log("后台测试任务已结束")
                with _state._test_lock:
                    total = _state._test_progress.get('total', 0)
                    processed = _state._test_progress.get('processed', 0)
                    if total and processed < total and not _state._test_progress.get('error'):
                        _state._test_progress['processed'] = total
                        _state._test_progress['failed'] = max(0, total - _state._test_progress.get('passed', 0))
                    _state._test_progress['running'] = False
                    _state._test_progress['finished_at'] = now_str()
                    _state._test_progress['elapsed'] = round(time.time() - _start_time, 1)
                    _state._test_progress['last_seq'] = _state._test_log_seq
                    _state.set_test_running(False)
                    _state.set_test_active_token(None)
            if is_current_run:
                try:
                    from database import clear_run_progress
                    clear_run_progress()
                except Exception:
                    pass

    t = threading.Thread(target=_run, daemon=True, name=f'test-{trigger_source}')
    t.start()
    return run_token

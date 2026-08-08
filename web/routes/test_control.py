# -*- coding: utf-8 -*-
"""web 包 — 测试控制 API 蓝图。"""
import json as _json
import os
import threading
import time
import uuid
from flask import Blueprint, request, jsonify, Response

import database as _db
import web.state as _state
from web.test_runner import _start_test_background
from web.scheduler import _scheduler_status

test_control_bp = Blueprint('test_control', __name__)

SSE_MAX_CONNECTIONS = 2
SSE_MAX_DURATION_SECONDS = 300
_TEST_TASK_OWNER = f"pid:{os.getpid()}:{uuid.uuid4().hex[:8]}"
_TEST_LEASE_SECONDS = 90
_TEST_HEARTBEAT_SECONDS = 2


class _SSESlot:
    def __init__(self, controller):
        self._controller = controller
        self._released = False
        self._lock = threading.Lock()

    def release(self):
        with self._lock:
            if self._released:
                return
            self._released = True
        self._controller._release()


class SSEAdmissionController:
    """Small process-global admission gate shared by every SSE endpoint."""

    def __init__(self, limit=SSE_MAX_CONNECTIONS):
        self.limit = int(limit)
        self._active = 0
        self._lock = threading.Lock()

    def try_acquire(self):
        with self._lock:
            if self._active >= self.limit:
                return None
            self._active += 1
        return _SSESlot(self)

    def _release(self):
        with self._lock:
            self._active = max(0, self._active - 1)

    @property
    def active(self):
        with self._lock:
            return self._active


sse_admission = SSEAdmissionController()


def acquire_sse_slot():
    return sse_admission.try_acquire()


def _monitor_test_task(task_id, owner):
    """Heartbeat the test lease and relay stop requests across workers."""
    try:
        _db.heartbeat_task_lease(
            'test', task_id, owner, state='running',
            lease_seconds=_TEST_LEASE_SECONDS, message='测速进行中',
        )
        while True:
            task = _db.get_task_lease('test')
            if not task or task.get('task_id') != task_id or not task.get('active'):
                with _state._test_lock:
                    _state._test_stop_event.set()
                return
            state = task.get('state')
            if state == 'stopping':
                with _state._test_lock:
                    _state._test_stop_event.set()
            with _state._test_lock:
                running = _state._test_running
            if not running:
                break
            if not _db.heartbeat_task_lease(
                'test', task_id, owner,
                state='stopping' if state == 'stopping' else 'running',
                lease_seconds=_TEST_LEASE_SECONDS,
            ):
                with _state._test_lock:
                    _state._test_stop_event.set()
                return
            time.sleep(_TEST_HEARTBEAT_SECONDS)

        task = _db.get_task_lease('test') or {}
        with _state._progress_lock:
            error = _state._test_progress.get('error') or ''
        if task.get('state') == 'stopping':
            _db.finish_task_lease(
                'test', task_id, state='cancelled', message='测速已停止', error=error
            )
        elif error:
            _db.finish_task_lease(
                'test', task_id, state='failed', message='测速失败', error=error
            )
        else:
            _db.finish_task_lease(
                'test', task_id, state='completed', message='测速完成'
            )
    except Exception as exc:
        with _state._test_lock:
            if _state._test_running:
                _state._test_stop_event.set()
        try:
            _db.finish_task_lease(
                'test', task_id, state='failed',
                message='测速监控异常', error=str(exc),
            )
        except Exception:
            pass
    finally:
        try:
            _db.close_thread_connection()
        except Exception:
            pass


@test_control_bp.route('/api/trigger', methods=['POST'])
def api_trigger():
    """触发一次测试运行。"""
    task_id = f"test-{uuid.uuid4().hex}"
    acquired, task = _db.acquire_task_lease(
        'test', task_id, _TEST_TASK_OWNER,
        lease_seconds=_TEST_LEASE_SECONDS, message='测速等待启动',
    )
    if not acquired:
        return jsonify({
            'ok': False,
            'error': '测试正在运行中，请等待完成',
            'data': task,
        }), 409

    if _start_test_background(trigger_source='web') is None:
        _db.finish_task_lease(
            'test', task_id, state='failed',
            message='本进程已有测速任务', error='本进程已有测速任务',
        )
        return jsonify({
            'ok': False,
            'error': '测试正在运行中，请等待完成',
            'data': _db.get_task_lease('test'),
        }), 409

    monitor = threading.Thread(
        target=_monitor_test_task,
        args=(task_id, _TEST_TASK_OWNER),
        daemon=True,
        name=f'test-lease-{task_id[-8:]}',
    )
    try:
        monitor.start()
    except Exception as exc:
        with _state._test_lock:
            _state._test_stop_event.set()
        _db.finish_task_lease(
            'test', task_id, state='failed',
            message='测速监控启动失败', error=str(exc),
        )
        return jsonify({
            'ok': False,
            'error': f'测试启动失败: {exc}',
            'data': _db.get_task_lease('test'),
        }), 500
    return jsonify({
        'ok': True,
        'message': '测试已启动',
        'task_id': task_id,
        'state': 'starting',
        'data': _db.get_task_lease('test'),
    }), 202


@test_control_bp.route('/api/stop', methods=['POST'])
def api_stop():
    """请求终止当前测试运行。"""
    data = request.get_json(silent=True) or {}
    msg = data.get('message', '用户手动终止')
    accepted, task = _db.request_task_stop('test', message=msg)
    if not accepted:
        return jsonify({
            'ok': False,
            'error': '当前没有正在运行的测试',
            'data': task,
        }), 409
    with _state._test_lock:
        if _state._test_running:
            _state._test_stop_event.set()
    with _state._progress_lock:
        if _state._test_progress.get('running'):
            _state._test_progress['error'] = msg
    return jsonify({
        'ok': True,
        'message': msg,
        'task_id': task.get('task_id'),
        'state': 'stopping',
        'data': task,
    }), 202


@test_control_bp.route('/api/tasks', methods=['GET'])
def api_tasks():
    """List the latest cross-process task snapshot for every task type."""
    active_only = request.args.get('active', '').strip().lower() in ('1', 'true', 'yes')
    all_items = _db.list_task_leases()
    items = [item for item in all_items if item.get('active')] if active_only else all_items
    snapshot = _db.get_tasks_snapshot(all_items)
    return jsonify({
        'ok': True,
        'data': {**snapshot, 'items': items},
    })


@test_control_bp.route('/api/tasks/<task_id>', methods=['GET'])
def api_task_detail(task_id):
    task = _db.get_task_lease_by_id(task_id)
    if not task:
        return jsonify({'ok': False, 'error': '任务不存在'}), 404
    return jsonify({'ok': True, 'data': task})


@test_control_bp.route('/api/status', methods=['GET'])
def api_status():
    """获取当前运行状态（精简版）。优先内存，其次 SQLite。"""
    scheduler_running, next_run_str = _scheduler_status()
    with _state._progress_lock:
        running = _state._test_progress['running']
        if running:
            processed = _state._test_progress['processed']
            total = _state._test_progress['total']
            elapsed = _state._test_progress['elapsed']
            source = _state._test_progress.get('source', 'web')
            sub_count = _state._test_progress.get('sub_count', 0)
            scan_count = _state._test_progress.get('scan_count', 0)
    if running:
        return jsonify({'ok': True, 'data': {
            'running': True,
            'processed': processed,
            'total': total,
            'elapsed': elapsed,
            'source': source,
            'sub_count': sub_count,
            'scan_count': scan_count,
            'next_scheduled_run': next_run_str,
            'scheduler_running': scheduler_running,
        }})
    from database import get_run_progress
    db_progress = get_run_progress()
    if db_progress and db_progress.get('running'):
        return jsonify({'ok': True, 'data': {
            'running': True,
            'processed': db_progress.get('processed', 0),
            'total': db_progress.get('total', 0),
            'elapsed': db_progress.get('elapsed', 0),
            'source': db_progress.get('source', 'scheduler'),
            'sub_count': db_progress.get('sub_count', 0),
            'scan_count': db_progress.get('scan_count', 0),
            'next_scheduled_run': next_run_str,
            'scheduler_running': scheduler_running,
        }})
    return jsonify({'ok': True, 'data': {
        'running': False,
        'processed': 0,
        'total': 0,
        'elapsed': 0,
        'source': '',
        'sub_count': 0,
        'scan_count': 0,
        'next_scheduled_run': next_run_str,
        'scheduler_running': scheduler_running,
    }})


@test_control_bp.route('/api/progress', methods=['GET'])
def api_progress():
    """获取实时进度和日志（支持增量拉取）。"""
    after = request.args.get('after', 0, type=int)
    scheduler_running, next_run_str = _scheduler_status()
    sched_info = {
        'next_scheduled_run': next_run_str,
        'scheduler_running': scheduler_running,
    }

    with _state._progress_lock:
        prog_running = _state._test_progress['running']
        if prog_running:
            prog_started_at = _state._test_progress['started_at']
            prog_total = _state._test_progress['total']
            prog_processed = _state._test_progress['processed']
            prog_passed = _state._test_progress['passed']
            prog_failed = _state._test_progress['failed']
            prog_elapsed = _state._test_progress['elapsed']
            prog_finished_at = _state._test_progress['finished_at']
            prog_error = _state._test_progress['error']
            prog_source = _state._test_progress.get('source', 'web')
            prog_sub_count = _state._test_progress.get('sub_count', 0)
            prog_scan_count = _state._test_progress.get('scan_count', 0)
            new_lines = [l for l in _state._test_log_lines if l['seq'] > after]
            prog_last_seq = _state._test_log_seq
    if prog_running:
        return jsonify({'ok': True, 'data': {
            'running': True,
            'started_at': prog_started_at,
            'total': prog_total,
            'processed': prog_processed,
            'passed': prog_passed,
            'failed': prog_failed,
            'elapsed': prog_elapsed,
            'finished_at': prog_finished_at,
            'error': prog_error,
            'lines': new_lines,
            'last_seq': prog_last_seq,
            'source': prog_source,
            'sub_count': prog_sub_count,
            'scan_count': prog_scan_count,
            **sched_info,
        }})

    from database import get_run_progress
    db_progress = get_run_progress()
    if db_progress and db_progress.get('running'):
        return jsonify({'ok': True, 'data': {
            'running': True,
            'started_at': db_progress.get('started_at'),
            'total': db_progress.get('total', 0),
            'processed': db_progress.get('processed', 0),
            'passed': db_progress.get('passed', 0),
            'failed': db_progress.get('failed', 0),
            'elapsed': db_progress.get('elapsed', 0),
            'finished_at': None,
            'error': None,
            'lines': [],
            'last_seq': 0,
            'source': db_progress.get('source', 'scheduler'),
            **sched_info,
        }})

    with _state._progress_lock:
        finished_at = _state._test_progress.get('finished_at')
    if finished_at:
        with _state._progress_lock:
            new_lines = [l for l in _state._test_log_lines if l['seq'] > after]
            started_at = _state._test_progress.get('started_at')
            total = _state._test_progress.get('total', 0)
            processed = _state._test_progress.get('processed', 0)
            passed = _state._test_progress.get('passed', 0)
            failed = _state._test_progress.get('failed', 0)
            elapsed = _state._test_progress.get('elapsed', 0)
            error = _state._test_progress.get('error')
            source = _state._test_progress.get('source', '')
            last_seq = _state._test_log_seq
        return jsonify({'ok': True, 'data': {
            'running': False,
            'started_at': started_at,
            'total': total,
            'processed': processed,
            'passed': passed,
            'failed': failed,
            'elapsed': elapsed,
            'finished_at': finished_at,
            'error': error,
            'lines': new_lines,
            'last_seq': last_seq,
            'source': source,
            **sched_info,
        }})

    with _state._progress_lock:
        last_finished_at = _state._test_progress.get('finished_at')
    return jsonify({'ok': True, 'data': {
        'running': False,
        'started_at': None,
        'total': 0,
        'processed': 0,
        'passed': 0,
        'failed': 0,
        'elapsed': 0,
        'finished_at': last_finished_at,
        'error': None,
        'lines': [],
        'last_seq': 0,
        'source': '',
        **sched_info,
    }})


@test_control_bp.route('/api/test/stream')
def api_test_stream():
    """SSE 实时推送测试进度和日志。"""
    slot = acquire_sse_slot()
    if slot is None:
        return jsonify({'ok': False, 'error': 'SSE 连接数已达上限'}), 429

    def generate():
        q = None
        deadline = time.monotonic() + SSE_MAX_DURATION_SECONDS
        try:
            q = _state.subscribe_test_sse()
            scheduler_running, next_run_str = _scheduler_status()
            with _state._progress_lock:
                prog = dict(_state._test_progress)
            snapshot = {
                'running': prog.get('running', False),
                'total': prog.get('total', 0),
                'processed': prog.get('processed', 0),
                'passed': prog.get('passed', 0),
                'failed': prog.get('failed', 0),
                'elapsed': prog.get('elapsed', 0),
                'source': prog.get('source', ''),
                'scheduler_running': scheduler_running,
                'next_scheduled_run': next_run_str,
            }
            yield f"event: status\ndata: {_json.dumps(snapshot, ensure_ascii=False)}\n\n"
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    yield f"event: error\ndata: {_json.dumps({'error': 'SSE 连接超时，请重新连接'})}\n\n"
                    break
                try:
                    msg = q.get(timeout=min(30, remaining))
                    yield msg
                except Exception:
                    yield ": heartbeat\n\n"
        except GeneratorExit:
            pass
        finally:
            if q is not None:
                _state.unsubscribe_test_sse(q)
            slot.release()

    response = Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        }
    )
    response.call_on_close(slot.release)
    return response

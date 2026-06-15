# -*- coding: utf-8 -*-
"""web 包 — 测试控制 API 蓝图。"""
from flask import Blueprint, request, jsonify

from web.state import (
    _test_progress,
    _test_log_lines,
    _test_log_seq,
    _test_running,
    _test_lock,
    _test_stop_event,
)
from web.test_runner import _start_test_background
from web.scheduler import _scheduler_status

test_control_bp = Blueprint('test_control', __name__)


@test_control_bp.route('/api/trigger', methods=['POST'])
def api_trigger():
    """触发一次测试运行。"""
    if _start_test_background(trigger_source='web') is not None:
        return jsonify({'ok': True, 'message': '测试已启动'})
    return jsonify({'error': '测试正在运行中，请等待完成'}), 409


@test_control_bp.route('/api/stop', methods=['POST'])
def api_stop():
    """请求终止当前测试运行。"""
    data = request.get_json(silent=True) or {}
    msg = data.get('message', '用户手动终止')
    with _test_lock:
        if not _test_running:
            return jsonify({'error': '当前没有正在运行的测试'}), 409
        _test_stop_event.set()
        _test_progress['error'] = msg
    return jsonify({'ok': True, 'message': msg})


@test_control_bp.route('/api/status', methods=['GET'])
def api_status():
    """获取当前运行状态（精简版）。优先内存，其次 SQLite。"""
    scheduler_running, next_run_str = _scheduler_status()
    if _test_progress['running']:
        return jsonify({
            'running': True,
            'processed': _test_progress['processed'],
            'total': _test_progress['total'],
            'elapsed': _test_progress['elapsed'],
            'source': _test_progress.get('source', 'web'),
            'next_scheduled_run': next_run_str,
            'scheduler_running': scheduler_running,
        })
    from database import get_run_progress
    db_progress = get_run_progress()
    if db_progress and db_progress.get('running'):
        return jsonify({
            'running': True,
            'processed': db_progress.get('processed', 0),
            'total': db_progress.get('total', 0),
            'elapsed': db_progress.get('elapsed', 0),
            'source': db_progress.get('source', 'scheduler'),
            'next_scheduled_run': next_run_str,
            'scheduler_running': scheduler_running,
        })
    return jsonify({
        'running': False,
        'processed': 0,
        'total': 0,
        'elapsed': 0,
        'source': '',
        'next_scheduled_run': next_run_str,
        'scheduler_running': scheduler_running,
    })


@test_control_bp.route('/api/progress', methods=['GET'])
def api_progress():
    """获取实时进度和日志（支持增量拉取）。"""
    after = request.args.get('after', 0, type=int)
    scheduler_running, next_run_str = _scheduler_status()
    sched_info = {
        'next_scheduled_run': next_run_str,
        'scheduler_running': scheduler_running,
    }

    if _test_progress['running']:
        new_lines = [l for l in _test_log_lines if l['seq'] > after]
        return jsonify({
            'running': True,
            'started_at': _test_progress['started_at'],
            'total': _test_progress['total'],
            'processed': _test_progress['processed'],
            'passed': _test_progress['passed'],
            'failed': _test_progress['failed'],
            'elapsed': _test_progress['elapsed'],
            'finished_at': _test_progress['finished_at'],
            'error': _test_progress['error'],
            'lines': new_lines,
            'last_seq': _test_log_seq,
            'source': _test_progress.get('source', 'web'),
            **sched_info,
        })

    from database import get_run_progress
    db_progress = get_run_progress()
    if db_progress and db_progress.get('running'):
        return jsonify({
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
        })

    if _test_progress.get('finished_at'):
        new_lines = [l for l in _test_log_lines if l['seq'] > after]
        return jsonify({
            'running': False,
            'started_at': _test_progress.get('started_at'),
            'total': _test_progress.get('total', 0),
            'processed': _test_progress.get('processed', 0),
            'passed': _test_progress.get('passed', 0),
            'failed': _test_progress.get('failed', 0),
            'elapsed': _test_progress.get('elapsed', 0),
            'finished_at': _test_progress.get('finished_at'),
            'error': _test_progress.get('error'),
            'lines': new_lines,
            'last_seq': _test_log_seq,
            'source': _test_progress.get('source', ''),
            **sched_info,
        })

    return jsonify({
        'running': False,
        'started_at': None,
        'total': 0,
        'processed': 0,
        'passed': 0,
        'failed': 0,
        'elapsed': 0,
        'finished_at': _test_progress.get('finished_at'),
        'error': None,
        'lines': [],
        'last_seq': 0,
        'source': '',
        **sched_info,
    })

# -*- coding: utf-8 -*-
"""web.routes.health — 健康检查端点，供 Docker / K8s / Nginx 监控使用。

路由:
    GET /api/health — api_health() 返回系统健康状态 JSON
"""
from flask import Blueprint, jsonify

from database import get_latest_run, get_scheduler_state, _get_conn
from web import state as _state

health_bp = Blueprint('health', __name__)


@health_bp.route('/api/health')
def api_health():
    """Health check endpoint for monitoring."""
    result = {
        'status': 'ok',
        'checks': {},
    }

    try:
        conn = _get_conn()
        conn.execute('SELECT 1')
        result['checks']['database'] = 'ok'
    except Exception as e:
        result['checks']['database'] = f'error: {e}'
        result['status'] = 'degraded'

    try:
        latest = get_latest_run()
        if latest:
            result['last_test'] = {
                'time': latest.get('finished_at'),
                'pass_rate': latest.get('pass_rate'),
                'total_passed': latest.get('total_passed'),
                'total_tested': latest.get('total_tested'),
            }
    except Exception:
        pass

    try:
        sched = get_scheduler_state()
        if sched:
            result['scheduler'] = {
                'running': bool(sched.get('running')),
                'next_run': sched.get('next_run'),
            }
    except Exception:
        pass

    result['test_running'] = bool(_state._test_running)

    return jsonify(result)

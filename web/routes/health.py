# -*- coding: utf-8 -*-
"""web.routes.health — 健康检查端点，供 Docker / K8s / Nginx 监控使用。

路由:
    GET /api/health — health_check() 返回系统健康状态 JSON
"""
import os
import time
import shutil

from flask import Blueprint, jsonify

from database import get_latest_run, get_scheduler_state, _get_conn
from web import state as _state

health_bp = Blueprint('health', __name__)

_START_TIME = time.time()


def _get_uptime():
    """返回服务运行时间（秒）"""
    return round(time.time() - _START_TIME, 2)


def _get_version():
    """从 CHANGELOG.md 读取最新版本号"""
    try:
        changelog = os.path.join(os.path.dirname(__file__), '..', '..', 'CHANGELOG.md')
        with open(changelog, 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('## ['):
                    return line.split('[')[1].split(']')[0]
    except Exception:
        pass
    return 'unknown'


@health_bp.route('/api/health', methods=['GET'])
def health_check():
    """增强的健康检查端点"""
    result = {
        'status': 'ok',
        'version': _get_version(),
        'uptime': _get_uptime(),
        'checks': {},
        'system': {}
    }

    # 数据库检查
    try:
        conn = _get_conn()
        conn.execute('SELECT 1')
        result['checks']['database'] = 'ok'
    except Exception as e:
        result['checks']['database'] = f'error: {e}'
        result['status'] = 'degraded'

    # FFmpeg 检查
    try:
        ffmpeg_path = os.environ.get('FFMPEG_BIN', 'ffmpeg')
        if shutil.which(ffmpeg_path):
            result['checks']['ffmpeg'] = 'ok'
        else:
            result['checks']['ffmpeg'] = 'not_found'
    except Exception:
        result['checks']['ffmpeg'] = 'error'

    # 磁盘空间检查
    try:
        import psutil
        disk = psutil.disk_usage('.')
        result['system']['disk_percent'] = disk.percent
        result['system']['disk_free_gb'] = round(disk.free / (1024**3), 2)
        if disk.percent > 90:
            result['checks']['disk'] = 'warning'
            result['status'] = 'degraded'
        else:
            result['checks']['disk'] = 'ok'
    except ImportError:
        pass
    except Exception:
        pass

    # 内存检查
    try:
        import psutil
        mem = psutil.virtual_memory()
        result['system']['memory_percent'] = mem.percent
        result['system']['memory_available_gb'] = round(mem.available / (1024**3), 2)
    except ImportError:
        pass
    except Exception:
        pass

    # 最近测试结果
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

    # 调度器状态
    try:
        sched = get_scheduler_state()
        if sched:
            result['scheduler'] = {
                'running': bool(sched.get('running')),
                'next_run': sched.get('next_run'),
            }
    except Exception:
        pass

    # 测试运行状态
    result['test_running'] = bool(_state._test_running)

    # 扫描模块状态
    try:
        from scanner_integration import bridge
        result['checks']['scanner'] = 'ok' if bridge and bridge._loop and bridge._loop.is_running() else 'not_running'
    except ImportError:
        result['checks']['scanner'] = 'not_available'
    except Exception:
        result['checks']['scanner'] = 'error'

    # 状态码：ok=200, degraded/warning=503
    status_code = 200 if result['status'] == 'ok' else 503
    return jsonify(result), status_code

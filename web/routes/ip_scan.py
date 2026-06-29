# -*- coding: utf-8 -*-
"""web 包 — IP扫描模块 API 蓝图。"""

import json
import logging
import threading
import time
import uuid
from datetime import datetime

from flask import Blueprint, request, jsonify, Response

import database as db
import web.state as _state
from web.routes.params import bounded_int, int_arg

logger = logging.getLogger(__name__)

ip_scan_bp = Blueprint('ip_scan', __name__)


def _get_ip_scanner():
    """获取 scanner_integration 模块。"""
    return _state._scanner_module


def _ensure_ip_scan_bridge():
    """确保IP扫描桥接层已初始化。"""
    scanner = _get_ip_scanner()
    if scanner is None:
        return None, jsonify({'ok': False, 'error': '扫描模块依赖未安装，请先安装 aiohttp: pip install aiohttp'}), 503
    return scanner, None, None


def _local_now():
    """获取本地时间"""
    try:
        from database import LOCAL_TZ
        return datetime.now(LOCAL_TZ).replace(tzinfo=None)
    except Exception:
        return datetime.now()


def _normalize_ports(raw_ports):
    """Normalize API-provided ports to a bounded, deduplicated list."""
    if raw_ports is None or raw_ports == '':
        raw_ports = [8080, 80, 443]
    if isinstance(raw_ports, str):
        raw_ports = raw_ports.replace('，', ',').replace(';', ',').split(',')
    if not isinstance(raw_ports, list):
        raw_ports = [8080, 80, 443]

    ports = []
    seen = set()
    for item in raw_ports:
        port = bounded_int(item, 0, 0, 65535)
        if 1 <= port <= 65535 and port not in seen:
            ports.append(port)
            seen.add(port)
        if len(ports) >= 100:
            break
    return ports or [8080, 80, 443]


def _normalize_scan_types(raw_types):
    """Return supported scan types only."""
    from scanner_integration.ip_scan_types import SCAN_TYPES

    if isinstance(raw_types, str):
        raw_types = [p.strip() for p in raw_types.replace('，', ',').split(',')]
    if not isinstance(raw_types, list):
        return []
    allowed = set(SCAN_TYPES)
    normalized = []
    for item in raw_types:
        value = str(item).strip().upper()
        if value in allowed and value not in normalized:
            normalized.append(value)
    return normalized


# ─────────────── IP扫描控制 API ───────────────

@ip_scan_bp.route('/api/ip-scan/trigger', methods=['POST'])
def api_ip_scan_trigger():
    """启动IP扫描。"""
    scanner, err, code = _ensure_ip_scan_bridge()
    if err:
        return err, code
    
    data = request.get_json(silent=True) or {}
    
    # 参数验证
    targets = str(data.get('targets', '')).strip()
    if not targets or not targets.strip():
        return jsonify({'ok': False, 'error': '请输入扫描目标'}), 400
    
    scan_types = _normalize_scan_types(data.get('scan_types', ['ALL']))
    if not scan_types:
        return jsonify({'ok': False, 'error': '请选择至少一种扫描类型'}), 400
    
    ports = _normalize_ports(data.get('ports', [8080, 80, 443]))
    workers = bounded_int(data.get('workers', 16), 16, 1, 100)
    rate_limit = bounded_int(data.get('rate_limit', 5000), 5000, 100, 50000)
    http_concurrent = bounded_int(data.get('http_concurrent', 50), 50, 1, 500)
    timeout = bounded_int(data.get('timeout', 3600), 3600, 60, 86400)
    
    # 调用扫描模块
    result = scanner.trigger_ip_scan(
        targets=targets,
        scan_types=scan_types,
        ports=ports,
        workers=workers,
        rate_limit=rate_limit,
        http_concurrent=http_concurrent,
        timeout=timeout
    )
    
    if 'error' in result:
        return jsonify({'ok': False, 'error': result['error']}), 409
    
    return jsonify({'ok': True, 'message': 'IP扫描已启动'})


@ip_scan_bp.route('/api/ip-scan/stop', methods=['POST'])
def api_ip_scan_stop():
    """请求停止IP扫描。"""
    scanner, err, code = _ensure_ip_scan_bridge()
    if err:
        return err, code
    
    result = scanner.request_stop_ip_scan()
    return jsonify({'ok': True, 'message': '已请求停止'})


@ip_scan_bp.route('/api/ip-scan/force-clear', methods=['POST'])
def api_ip_scan_force_clear():
    """强制清除IP扫描状态。"""
    try:
        db.reset_ip_scan_progress()
        return jsonify({'ok': True, 'message': '状态已清除'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


@ip_scan_bp.route('/api/ip-scan/status', methods=['GET'])
def api_ip_scan_status():
    """获取IP扫描状态。"""
    try:
        progress = db.get_ip_scan_progress()
        return jsonify({'ok': True, 'data': progress})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


@ip_scan_bp.route('/api/ip-scan/logs', methods=['GET'])
def api_ip_scan_logs():
    """获取IP扫描日志（短轮询增量拉取）。"""
    try:
        after = int_arg(request.args, 'after', 0, 0, None)
        limit = int_arg(request.args, 'limit', 500, 1, 1000)
        lines = db.get_ip_scan_logs(after, limit)
        last_seq = lines[-1]['seq'] if lines else after
        return jsonify({'ok': True, 'data': {'lines': lines, 'last_seq': last_seq}})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


@ip_scan_bp.route('/api/ip-scan/stream', methods=['GET'])
def api_ip_scan_stream():
    """SSE实时推送IP扫描进度和日志。"""
    scanner, err, code = _ensure_ip_scan_bridge()
    if err:
        return err, code
    
    def generate():
        q = scanner.subscribe_ip_scan_sse()
        try:
            progress = scanner.get_ip_scan_status()
            yield f"event: status\ndata: {json.dumps(progress, ensure_ascii=False)}\n\n"
            while True:
                try:
                    msg = q.get(timeout=30)
                    yield msg
                except Exception:
                    # 发送心跳保活
                    yield ": heartbeat\n\n"
        except GeneratorExit:
            pass
        finally:
            scanner.unsubscribe_ip_scan_sse(q)
    
    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no'
        }
    )


# ─────────────── IP扫描结果 API ───────────────

@ip_scan_bp.route('/api/ip-scan/results', methods=['GET'])
def api_ip_scan_results():
    """查询IP扫描结果。"""
    scan_id = request.args.get('scan_id')
    page = int_arg(request.args, 'page', 1, 1, None)
    size = int_arg(request.args, 'size', 20, 1, 200)
    
    try:
        results = db.get_ip_scan_results(scan_id, page, size)
        return jsonify({'ok': True, 'data': results})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


@ip_scan_bp.route('/api/ip-scan/latest', methods=['GET'])
def api_ip_scan_latest():
    """获取最新一次IP扫描记录。"""
    try:
        latest = db.get_latest_ip_scan_run()
        return jsonify({'ok': True, 'data': latest})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


@ip_scan_bp.route('/api/ip-scan/history', methods=['GET'])
def api_ip_scan_history():
    """获取IP扫描历史。"""
    try:
        limit = int_arg(request.args, 'limit', 20, 1, 100)
        history = db.get_ip_scan_history(limit)
        return jsonify({'ok': True, 'data': history})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


@ip_scan_bp.route('/api/ip-scan/stats', methods=['GET'])
def api_ip_scan_stats():
    """获取IP扫描统计。"""
    scan_id = request.args.get('scan_id')
    try:
        stats = db.get_ip_scan_stats(scan_id)
        return jsonify({'ok': True, 'data': stats})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


# ─────────────── IP扫描结果操作 API ───────────────

@ip_scan_bp.route('/api/ip-scan/to-test', methods=['POST'])
def api_ip_scan_to_test():
    """将IP扫描结果送入测速。"""
    data = request.get_json(silent=True) or {}
    scan_id = data.get('scan_id')
    selected = data.get('selected', [])
    
    if not scan_id:
        return jsonify({'ok': False, 'error': '缺少scan_id'}), 400
    
    try:
        # 获取选中的频道
        channels = db.get_ip_scan_channels(scan_id, selected)
        
        if not channels:
            return jsonify({'ok': False, 'error': '没有找到可测速的频道'}), 400
        
        # 送入测速流水线
        scanner = _get_ip_scanner()
        if scanner:
            result = scanner.send_channels_to_test(channels)
            return jsonify({'ok': True, 'message': f'已送入 {len(channels)} 个频道', 'data': result})
        else:
            return jsonify({'ok': False, 'error': '扫描模块未初始化'}), 503
            
    except Exception as e:
        logger.error(f"送入测速失败: {e}")
        return jsonify({'ok': False, 'error': str(e)})


@ip_scan_bp.route('/api/ip-scan/export', methods=['GET'])
def api_ip_scan_export():
    """导出IP扫描结果为M3U。"""
    scan_id = request.args.get('scan_id')
    if not scan_id:
        return jsonify({'ok': False, 'error': '缺少scan_id'}), 400
    
    try:
        channels = db.get_ip_scan_all_channels(scan_id)
        
        if not channels:
            return jsonify({'ok': False, 'error': '没有可导出的频道'}), 404
        
        # 生成M3U内容
        lines = ['#EXTM3U']
        for ch in channels:
            name = ch.get('name', '未知')
            url = ch.get('url', '')
            if url:
                lines.append(f'#EXTINF:-1,{name}')
                lines.append(url)
        
        content = '\n'.join(lines)
        
        return Response(
            content,
            mimetype='audio/x-mpegurl',
            headers={
                'Content-Disposition': f'attachment; filename=ip_scan_{scan_id[:8]}.m3u'
            }
        )
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

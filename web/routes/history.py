# -*- coding: utf-8 -*-
"""web.routes.history — 测试历史 API。

路由:
    GET    /api/runs               — api_get_runs() 测试历史列表
    GET    /api/run/<run_id>        — api_get_run() 单轮详情
    GET    /api/run/<run_id>/channels — api_get_run_channels() 频道分组详情（分页）
    DELETE /api/run/<run_id>        — api_delete_run() 删除记录
    GET    /api/run/<run_id>/logs   — api_get_run_logs() 运行日志
    GET    /api/compare             — api_compare_runs() 对比两轮测试
    GET    /api/sources             — api_get_sources() 订阅源质量评分
    GET    /api/channel/<name>/trend — api_channel_trend() 频道质量趋势
"""
from flask import Blueprint, request, jsonify

from database import (
    get_run_history,
    get_run_detail,
    get_channel_summary_with_source,
    delete_run,
    get_run_logs,
    compare_runs,
)
from web.routes.params import int_arg
from web.dashboard_service import get_dashboard, get_sources_page

history_bp = Blueprint('history', __name__)


@history_bp.route('/api/dashboard', methods=['GET'])
def api_dashboard():
    """Return SQL-aggregated scan, subscription and task quality metrics."""
    trend_limit = int_arg(request.args, 'trend_limit', 10, 1, 30)
    return jsonify({'ok': True, 'data': get_dashboard(trend_limit=trend_limit)})


# ─────────────── 测试历史 API ───────────────

@history_bp.route('/api/runs', methods=['GET'])
def api_get_runs():
    """获取测试历史列表。支持日期筛选：?start=2026-05-01&end=2026-05-26"""
    start = request.args.get('start', '')
    end = request.args.get('end', '')
    runs = get_run_history(start_date=start or None, end_date=end or None)
    return jsonify({'ok': True, 'items': runs, 'total': len(runs)})


@history_bp.route('/api/run/<run_id>', methods=['GET'])
def api_get_run(run_id):
    """获取单轮测试详情。"""
    detail = get_run_detail(run_id)
    if not detail:
        return jsonify({'ok': False, 'error': '未找到该轮记录'}), 404
    return jsonify({'ok': True, 'data': detail})


@history_bp.route('/api/run/<run_id>/channels', methods=['GET'])
def api_get_run_channels(run_id):
    """获取单轮测试按频道分组的详情，含数据来源平台。"""
    page = int_arg(request.args, 'page', 1, 1, None)
    size = int_arg(request.args, 'size', 20, 1, 200)
    summary = get_channel_summary_with_source(run_id, page=page, size=size)
    return jsonify({'ok': True, 'data': summary})


@history_bp.route('/api/run/<run_id>', methods=['DELETE'])
def api_delete_run(run_id):
    """删除指定轮次记录。"""
    delete_run(run_id)
    return jsonify({'ok': True})


@history_bp.route('/api/run/<run_id>/logs', methods=['GET'])
def api_get_run_logs(run_id):
    """获取指定轮次的运行日志。"""
    limit = int_arg(request.args, 'limit', 0, 0, 5000)
    payload = get_run_logs(run_id, limit=limit if limit and limit > 0 else None)
    return jsonify({'ok': True, 'data': payload})


# ─────────────── 测试对比 API ───────────────

@history_bp.route('/api/compare', methods=['GET'])
def api_compare_runs():
    """对比两轮测试结果。?run_a=<id>&run_b=<id>"""
    run_a = request.args.get('run_a', '').strip()
    run_b = request.args.get('run_b', '').strip()
    if not run_a or not run_b:
        return jsonify({'ok': False, 'error': '请提供 run_a 和 run_b 参数'}), 400
    result = compare_runs(run_a, run_b)
    if result is None:
        return jsonify({'ok': False, 'error': '未找到指定轮次'}), 404
    return jsonify({'ok': True, 'data': result})


# ─────────────── 订阅源质量评分 API ───────────────

@history_bp.route('/api/sources', methods=['GET'])
def api_get_sources():
    """Return server-paginated/searchable/sortable source quality scores."""
    page = int_arg(request.args, 'page', 1, 1, None)
    size = int_arg(request.args, 'size', 20, 1, 200)
    data = get_sources_page(
        page=page,
        size=size,
        search=request.args.get('search', ''),
        sort_by=request.args.get('sort_by', 'score'),
        sort_order=request.args.get('sort_order', 'desc'),
        reveal_url=request.args.get('reveal_url', '').lower() in ('1', 'true'),
    )
    return jsonify({'ok': True, 'data': data})


# ─────────────── 频道质量趋势 API ───────────────

@history_bp.route('/api/channel/<path:name>/trend')
def api_channel_trend(name):
    """Get quality trend for a specific channel across runs."""
    from database import _get_conn
    limit = int_arg(request.args, 'limit', 20, 5, 100)

    conn = _get_conn()
    rows = conn.execute("""
        SELECT r.run_id, r.finished_at,
               res.bandwidth_MBps, res.connection_latency_ms,
               res.quality_score, res.resolution, res.codec, res.passed
        FROM run_results res
        JOIN runs r ON res.run_id = r.run_id
        WHERE res.channel = %s
        ORDER BY r.id DESC
        LIMIT %s
    """, (name, limit * 10)).fetchall()

    by_run = {}
    for row in rows:
        rid = row['run_id']
        if rid not in by_run:
            by_run[rid] = {
                'run_id': rid,
                'finished_at': row['finished_at'],
                'best_passed': None,
                'best_overall': None,
            }
        entry = dict(row)
        if row['passed']:
            if by_run[rid]['best_passed'] is None or (row['quality_score'] or 0) > (by_run[rid]['best_passed'].get('quality_score') or 0):
                by_run[rid]['best_passed'] = entry
        if by_run[rid]['best_overall'] is None or (row['quality_score'] or 0) > (by_run[rid]['best_overall'].get('quality_score') or 0):
            by_run[rid]['best_overall'] = entry

    trend = []
    for rid, data in sorted(by_run.items(), key=lambda x: x[1]['finished_at'] or '', reverse=True)[:limit]:
        best = data['best_passed'] or data['best_overall']
        if best:
            trend.append({
                'run_id': data['run_id'],
                'finished_at': data['finished_at'],
                'bandwidth_MBps': best['bandwidth_MBps'],
                'connection_latency_ms': best['connection_latency_ms'],
                'quality_score': best['quality_score'],
                'resolution': best['resolution'],
                'codec': best['codec'],
                'passed': bool(best['passed']),
            })

    trend.reverse()
    return jsonify({'ok': True, 'data': {'channel': name, 'trend': trend}})

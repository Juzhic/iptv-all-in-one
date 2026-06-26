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
from collections import defaultdict

from flask import Blueprint, request, jsonify

from database import (
    get_run_history,
    get_run_detail,
    get_channel_summary_with_source,
    delete_run,
    get_run_logs,
    get_latest_run,
    get_config_data,
    compare_runs,
)
from web.routes.params import int_arg

history_bp = Blueprint('history', __name__)


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

def _count_template_channels():
    """从 demo 模板中解析频道总数（去重）。"""
    raw = get_config_data('demo')
    if not raw:
        return 0
    channels = set()
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.endswith(',#genre#') or line.startswith('#'):
            continue
        channels.add(line)
    return len(channels)


@history_bp.route('/api/sources', methods=['GET'])
def api_get_sources():
    """获取最新一轮测试中各订阅源的质量评分。"""
    run = get_latest_run()
    if not run:
        return jsonify({'ok': True, 'data': {'sources': [], 'last_updated': None}})

    results = run.get('results', [])
    if not results:
        return jsonify({'ok': True, 'data': {'sources': [], 'last_updated': run.get('finished_at')}})

    template_total = _count_template_channels()

    # 按 source_url 分组
    by_source = defaultdict(list)
    for r in results:
        url = (r.get('source_url') or '').strip()
        if not url:
            url = '(未知来源)'
        by_source[url].append(r)

    sources = []
    for src_url, items in by_source.items():
        channels = set()
        passed_channels = set()
        bw_list = []
        qs_list = []
        h265_count = 0

        for r in items:
            ch = r.get('channel', '')
            channels.add(ch)
            if r.get('passed'):
                passed_channels.add(ch)
                bw = r.get('bandwidth_MBps')
                if bw is not None and bw > 0:
                    bw_list.append(bw)
                qs = r.get('quality_score')
                if qs is not None and qs > 0:
                    qs_list.append(qs)
            if r.get('is_h265'):
                h265_count += 1

        ch_total = len(channels)
        ch_passed = len(passed_channels)
        pass_rate = ch_passed / ch_total if ch_total > 0 else 0
        avg_bw = sum(bw_list) / len(bw_list) if bw_list else 0
        avg_qs = sum(qs_list) / len(qs_list) if qs_list else 0
        h265_ratio = h265_count / len(items) if items else 0
        coverage = ch_passed / template_total if template_total > 0 else 0

        score = (
            coverage * 30
            + pass_rate * 30
            + min(avg_bw / 10, 1) * 20
            + min(avg_qs / 5, 1) * 20
        )

        sources.append({
            'source_url': src_url,
            'channels_total': ch_total,
            'channels_passed': ch_passed,
            'pass_rate': round(pass_rate, 4),
            'avg_bandwidth': round(avg_bw, 2),
            'avg_quality': round(avg_qs, 2),
            'h265_ratio': round(h265_ratio, 4),
            'score': round(score, 1),
        })

    sources.sort(key=lambda s: s['score'], reverse=True)
    return jsonify({'ok': True, 'data': {'sources': sources, 'last_updated': run.get('finished_at')}})


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

# -*- coding: utf-8 -*-
"""web.routes.history — 测试历史 API。

路由:
    GET    /api/runs               — api_get_runs() 测试历史列表
    GET    /api/run/<run_id>        — api_get_run() 单轮详情
    GET    /api/run/<run_id>/channels — api_get_run_channels() 频道分组详情（分页）
    DELETE /api/run/<run_id>        — api_delete_run() 删除记录
    GET    /api/run/<run_id>/logs   — api_get_run_logs() 运行日志
"""
from flask import Blueprint, request, jsonify

from database import (
    get_run_history,
    get_run_detail,
    get_channel_summary_with_source,
    delete_run,
    get_run_logs,
)

history_bp = Blueprint('history', __name__)


# ─────────────── 测试历史 API ───────────────

@history_bp.route('/api/runs', methods=['GET'])
def api_get_runs():
    """获取测试历史列表。支持日期筛选：?start=2026-05-01&end=2026-05-26"""
    start = request.args.get('start', '')
    end = request.args.get('end', '')
    runs = get_run_history(start_date=start or None, end_date=end or None)
    return jsonify(runs)


@history_bp.route('/api/run/<run_id>', methods=['GET'])
def api_get_run(run_id):
    """获取单轮测试详情。"""
    detail = get_run_detail(run_id)
    if not detail:
        return jsonify({'error': '未找到该轮记录'}), 404
    return jsonify(detail)


@history_bp.route('/api/run/<run_id>/channels', methods=['GET'])
def api_get_run_channels(run_id):
    """获取单轮测试按频道分组的详情，含数据来源平台。"""
    page = request.args.get('page', type=int)
    size = request.args.get('size', 20, type=int)
    summary = get_channel_summary_with_source(run_id, page=page, size=size)
    return jsonify(summary)


@history_bp.route('/api/run/<run_id>', methods=['DELETE'])
def api_delete_run(run_id):
    """删除指定轮次记录。"""
    delete_run(run_id)
    return jsonify({'ok': True})


@history_bp.route('/api/run/<run_id>/logs', methods=['GET'])
def api_get_run_logs(run_id):
    """获取指定轮次的运行日志。"""
    limit = request.args.get('limit', 0, type=int)
    payload = get_run_logs(run_id, limit=limit if limit and limit > 0 else None)
    return jsonify(payload)

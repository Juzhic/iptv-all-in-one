# -*- coding: utf-8 -*-
"""web.routes.spa — SPA 页面与初始数据 API。

路由:
    GET  /                  — index() 服务 Vue SPA 入口
    GET  /static/dist/…    — serve_spa_assets() 静态构建产物
    GET  /api/initial       — api_initial() 初始数据接口
"""
import os

from flask import Blueprint, jsonify, request, send_file, send_from_directory

from database import (
    get_latest_run,
    get_run_history,
    get_channel_summary,
    get_codec_stats,
    get_latest_scan_run,
)
from web.app import DIST_DIR, _ensure_frontend

spa_bp = Blueprint('spa', __name__)


# ─────────────── 页面路由 ───────────────

@spa_bp.route('/')
def index():
    """服务 Vue SPA 入口文件。"""
    spa_path = os.path.join(DIST_DIR, 'index.html')
    if os.path.exists(spa_path):
        return send_file(spa_path)
    _ensure_frontend()
    if os.path.exists(spa_path):
        return send_file(spa_path)
    return '前端未构建，请先执行: cd frontend && npm run build', 500


@spa_bp.route('/static/dist/<path:filename>')
def serve_spa_assets(filename):
    """服务 Vue SPA 构建产物（JS/CSS/图片等）。"""
    if not os.path.isdir(DIST_DIR):
        _ensure_frontend()
    return send_from_directory(DIST_DIR, filename)


@spa_bp.route('/api/initial')
def api_initial():
    """为 Vue SPA 提供初始数据（替代 Jinja2 服务端渲染）。"""
    runs = get_run_history()
    include_details = request.args.get('include_details', '').lower() in (
        '1', 'true', 'yes', 'on'
    )
    latest = runs[0] if runs else None
    channel_summary = {}
    codec_stats = {}

    if include_details:
        latest = get_latest_run()
        if latest and latest.get('results'):
            channel_summary = get_channel_summary(latest['run_id'])
            codec_stats = get_codec_stats(latest['run_id'])

    return jsonify({
        'latest': latest,
        'latest_scan': get_latest_scan_run(),
        'runs': runs,
        'channel_summary': channel_summary,
        'codec_stats': codec_stats,
    })

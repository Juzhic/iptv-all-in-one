# -*- coding: utf-8 -*-
"""web 包 — 结果下载 API 蓝图。"""
import io

from flask import Blueprint, jsonify, send_file

from database import get_latest_run, get_latest_passed_results
from web.result_gen import _generate_result_txt, _generate_result_m3u

download_bp = Blueprint('download', __name__)


@download_bp.route('/api/download/<fmt>', methods=['GET'])
def api_download(fmt):
    """下载结果文件（从数据库动态生成）。"""
    if fmt not in ('txt', 'm3u'):
        return jsonify({'ok': False, 'error': '格式仅支持 txt 或 m3u'}), 400

    latest_run = get_latest_run()
    passed = get_latest_passed_results()
    if not passed:
        return jsonify({'ok': False, 'error': '暂无通过的频道数据'}), 404
    fallback_update_time = (latest_run or {}).get('finished_at')

    if fmt == 'txt':
        content = _generate_result_txt(passed, fallback_update_time)
        filename = 'result.txt'
        mimetype = 'text/plain'
    else:
        content = _generate_result_m3u(passed, fallback_update_time)
        filename = 'result.m3u'
        mimetype = 'application/x-mpegurl'

    buf = io.BytesIO(content.encode('utf-8'))
    buf.seek(0)
    return send_file(buf, mimetype=mimetype, as_attachment=True, download_name=filename)

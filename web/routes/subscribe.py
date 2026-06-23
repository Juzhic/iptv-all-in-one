# -*- coding: utf-8 -*-
"""web.routes.subscribe — 动态 M3U 订阅代理端点。"""
import io

from flask import Blueprint, Response, request, send_file

from database import get_latest_run, get_latest_passed_results
from web.result_gen import _generate_result_txt, _generate_result_m3u

subscribe_bp = Blueprint('subscribe', __name__)


def _build_channel_genre_map(demo_content=None):
    """从 demo 模板构建 {频道名: 分类名} 映射。"""
    try:
        from engine.test_engine import parse_demo_file
        demo = parse_demo_file(demo_content)
        mapping = {}
        for genre, ch_list in demo:
            for ch in ch_list:
                mapping[ch] = genre
        return mapping
    except Exception:
        return {}


def _get_passed_results_with_codec(codec_filter=None, min_bw=None):
    """当需要按 codec 或带宽精确过滤时，直接查询数据库。"""
    from database import _get_conn
    conn = _get_conn()
    run = conn.execute("SELECT run_id FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    if not run:
        return []

    where = "WHERE run_id = %s AND passed = 1"
    params = [run['run_id']]

    if codec_filter == 'h265':
        where += " AND is_h265 = 1"
    elif codec_filter == 'h264':
        where += " AND (is_h265 = 0 OR is_h265 IS NULL)"

    if min_bw is not None:
        where += " AND COALESCE(bandwidth_MBps, 0) >= %s"
        params.append(min_bw)

    rows = conn.execute(
        f"""SELECT channel, url, bandwidth_MBps, connection_latency_ms,
                   quality_score, output_updated_at, is_h265, codec
            FROM run_results
            {where}
            ORDER BY channel,
                     COALESCE(quality_score, 0) DESC,
                     COALESCE(bandwidth_MBps, 0) DESC,
                     COALESCE(connection_latency_ms, 999999999) ASC,
                     id""",
        params
    ).fetchall()
    return [dict(r) for r in rows]


@subscribe_bp.route('/api/subscribe.m3u')
def api_subscribe():
    """动态 M3U 订阅端点，供 IPTV 播放器直接订阅。

    Query parameters:
        category: 按分类过滤（如 央视频道、卫视频道）
        province: 按省份过滤（如 广东）
        codec: 按编码过滤（h265、h264）
        min_bandwidth: 最低带宽（MB/s）
        format: 输出格式，m3u（默认）或 txt
        profile: 频道方案名称（如不指定则使用默认 demo）
    """
    category = request.args.get('category', '').strip()
    province = request.args.get('province', '').strip()
    codec = request.args.get('codec', '').strip().lower()
    min_bw = request.args.get('min_bandwidth', type=float)
    fmt = request.args.get('format', 'm3u').strip().lower()
    profile = request.args.get('profile', '').strip()

    demo_content = None
    if profile:
        from database import get_config_data
        demo_content = get_config_data(f'profile:{profile}')
        if not demo_content:
            demo_content = None

    latest_run = get_latest_run()
    fallback_update_time = (latest_run or {}).get('finished_at')

    need_db_query = codec or (min_bw is not None)
    if need_db_query:
        passed = _get_passed_results_with_codec(
            codec_filter=codec or None,
            min_bw=min_bw,
        )
    else:
        passed = get_latest_passed_results()

    if not passed:
        empty = '#EXTM3U\n# No channels available\n'
        if fmt == 'txt':
            empty = '# No channels available\n'
        return Response(empty, mimetype='audio/x-mpegurl' if fmt != 'txt' else 'text/plain',
                       headers={'Content-Disposition': 'attachment; filename=iptv.' + ('txt' if fmt == 'txt' else 'm3u')})

    if category or province:
        genre_map = _build_channel_genre_map(demo_content)
        filtered = []
        for r in passed:
            ch = r['channel']
            genre = genre_map.get(ch, '')
            if category and category not in genre:
                continue
            if province and province not in ch and province not in genre:
                continue
            filtered.append(r)
        passed = filtered

    if not passed:
        empty = '#EXTM3U\n# No channels match filters\n'
        if fmt == 'txt':
            empty = '# No channels match filters\n'
        return Response(empty, mimetype='audio/x-mpegurl' if fmt != 'txt' else 'text/plain',
                       headers={'Content-Disposition': 'attachment; filename=iptv.' + ('txt' if fmt == 'txt' else 'm3u')})

    if fmt == 'txt':
        content = _generate_result_txt(passed, fallback_update_time)
        buf = io.BytesIO(content.encode('utf-8'))
        buf.seek(0)
        return send_file(buf, mimetype='text/plain',
                        as_attachment=True, download_name='iptv.txt')
    else:
        content = _generate_result_m3u(passed, fallback_update_time)
        buf = io.BytesIO(content.encode('utf-8'))
        buf.seek(0)
        return send_file(buf, mimetype='audio/x-mpegurl',
                        as_attachment=True, download_name='iptv.m3u')

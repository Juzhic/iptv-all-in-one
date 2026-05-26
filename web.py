"""IPTV 测速管理后台 — Web 服务。"""
import collections
import json
import os
import threading
import time
from datetime import datetime, timedelta

from flask import Flask, render_template, request, jsonify, send_file
from db import (
    init_db, migrate_from_json,
    get_latest_run, get_latest_passed_results,
    get_run_history, get_run_detail, get_channel_summary,
    get_codec_stats, delete_run,
    get_config_data, set_config_data, DEFAULT_DEMO,
    get_config, save_config as db_save_config,
)
from app import load_config, DEFAULT_CONFIG

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True

# 初始化数据库（模块加载时执行，兼容 uWSGI / gunicorn 等 WSGI 服务器）
init_db()
migrate_from_json()


@app.after_request
def add_no_cache_headers(response):
    """禁止浏览器缓存页面，确保每次刷新都获取最新内容。"""
    if 'text/html' in response.content_type:
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response

# 允许通过 Web 编辑的数据 key
ALLOWED_DATA_KEYS = {'alias', 'demo', 'subscribe'}

# 测试运行状态锁
_test_running = False
_test_lock = threading.Lock()

# 测试进度追踪（模块级）
_test_progress = {
    'running': False,
    'started_at': None,
    'total': 0,
    'processed': 0,
    'passed': 0,
    'failed': 0,
    'elapsed': 0,
    'finished_at': None,
    'error': None,
}
_test_log_lines = collections.deque(maxlen=200)  # 环形缓冲，最多 200 行日志
_test_log_seq = 0  # 日志序号，用于增量拉取


# ─────────────── 页面路由 ───────────────

@app.route('/')
def index():
    """渲染主页面（仪表盘 + 配置管理）。"""
    latest = get_latest_run()
    runs = get_run_history()

    channel_summary = {}
    codec_stats = {}
    if latest and latest.get('results'):
        channel_summary = get_channel_summary(latest['run_id'])
        codec_stats = get_codec_stats(latest['run_id'])

    return render_template(
        'index.html',
        latest=latest,
        runs=runs,
        channel_summary=channel_summary,
        codec_stats=codec_stats,
    )


# ─────────────── 配置 API ───────────────

@app.route('/api/config', methods=['GET'])
def api_get_config():
    """读取当前配置（从数据库，合并默认值）。"""
    cfg = load_config()
    return jsonify(cfg)


@app.route('/api/config', methods=['POST'])
def api_save_config():
    """保存配置到数据库。"""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': '无效的请求数据'}), 400

    # 合法配置项白名单
    valid_keys = set(DEFAULT_CONFIG.keys())
    valid_keys.add('web_port')

    # 读取当前配置，只更新合法 key
    cfg = get_config(DEFAULT_CONFIG)
    updated_keys = []
    for key, value in data.items():
        if key in valid_keys:
            cfg[key] = value
            updated_keys.append(key)

    # 规范化 run_times
    if 'run_times' in updated_keys:
        cfg['run_times'] = _normalize_run_times(cfg['run_times'])

    db_save_config(cfg)
    return jsonify({'ok': True, 'updated': updated_keys, 'config': cfg})


def _normalize_run_times(times):
    """规范化时间列表输入：补零、去重、排序、校验范围。"""
    if isinstance(times, str):
        times = [t.strip() for t in times.replace(';', ',').replace('，', ',').split(',') if t.strip()]
    if not isinstance(times, list):
        return []
    result = []
    for t in times:
        t = str(t).strip()
        if not t:
            continue
        parts = t.split(':')
        if len(parts) != 2:
            continue
        try:
            h, m = int(parts[0]), int(parts[1])
            if 0 <= h <= 23 and 0 <= m <= 59:
                result.append(f'{h:02d}:{m:02d}')
        except ValueError:
            continue
    # 去重排序
    return sorted(set(result))


# ─────────────── 数据文件 API ───────────────

@app.route('/api/text/<key>', methods=['GET'])
def api_get_text(key):
    """读取配置数据内容。"""
    if key not in ALLOWED_DATA_KEYS:
        return jsonify({'error': '不允许访问该数据'}), 403
    content = get_config_data(key)
    return jsonify({'content': content, 'filename': key})


@app.route('/api/text/<key>', methods=['POST'])
def api_save_text(key):
    """保存配置数据内容。"""
    if key not in ALLOWED_DATA_KEYS:
        return jsonify({'error': '不允许访问该数据'}), 403
    data = request.get_json(silent=True)
    if not data or 'content' not in data:
        return jsonify({'error': '缺少 content 字段'}), 400
    set_config_data(key, data['content'])
    return jsonify({'ok': True, 'filename': key})


@app.route('/api/reset-demo', methods=['POST'])
def api_reset_demo():
    """恢复 demo 模板为默认内容。"""
    set_config_data('demo', DEFAULT_DEMO)
    return jsonify({'ok': True, 'message': '已恢复默认模板'})


# ─────────────── 测试历史 API ───────────────

@app.route('/api/runs', methods=['GET'])
def api_get_runs():
    """获取测试历史列表。支持日期筛选：?start=2026-05-01&end=2026-05-26"""
    start = request.args.get('start', '')
    end = request.args.get('end', '')
    runs = get_run_history(start_date=start or None, end_date=end or None)
    return jsonify(runs)


@app.route('/api/run/<run_id>', methods=['GET'])
def api_get_run(run_id):
    """获取单轮测试详情。"""
    detail = get_run_detail(run_id)
    if not detail:
        return jsonify({'error': '未找到该轮记录'}), 404
    return jsonify(detail)


@app.route('/api/run/<run_id>', methods=['DELETE'])
def api_delete_run(run_id):
    """删除指定轮次记录。"""
    delete_run(run_id)
    return jsonify({'ok': True})


@app.route('/api/run/<run_id>/logs', methods=['GET'])
def api_get_run_logs(run_id):
    """获取指定轮次的运行日志。"""
    limit = request.args.get('limit', 500, type=int)
    from db import get_run_logs
    logs = get_run_logs(run_id, limit=limit)
    return jsonify(logs)


# ─────────────── 结果下载 API ───────────────

def _result_sort_key(result):
    score = result.get('quality_score')
    if score is None:
        bandwidth = result.get('bandwidth_MBps') or 0
        latency = result.get('connection_latency_ms')
        try:
            latency_seconds = max(float(latency), 0) / 1000
        except (TypeError, ValueError):
            latency_seconds = 3
        score = float(bandwidth or 0) / (1 + latency_seconds)
    try:
        bandwidth = float(result.get('bandwidth_MBps') or 0)
    except (TypeError, ValueError):
        bandwidth = 0
    try:
        latency_sort = float(result.get('connection_latency_ms'))
    except (TypeError, ValueError):
        latency_sort = 999999999
    return (-float(score or 0), -bandwidth, latency_sort, result.get('url', ''))


def _get_max_urls_per_channel():
    cfg = load_config()
    try:
        return max(0, int(cfg.get('max_urls_per_channel', 0) or 0))
    except (TypeError, ValueError):
        return 0


def _group_passed_results(passed_results):
    channels = collections.OrderedDict()
    for r in sorted(passed_results, key=_result_sort_key):
        ch = r['channel']
        if ch not in channels:
            channels[ch] = []
        channels[ch].append(r)
    return channels


def _results_for_channel(ch, channels, name_to_canonical=None, regex_aliases=None):
    results = channels.get(ch, [])
    if not results and name_to_canonical:
        from app import match_channel_name
        canonical = match_channel_name(ch, name_to_canonical, regex_aliases)
        if canonical and canonical != ch:
            results = channels.get(canonical, [])
    max_urls = _get_max_urls_per_channel()
    if max_urls > 0:
        return results[:max_urls]
    return results

def _generate_result_txt(passed_results):
    """从通过的结果动态生成 result.txt 格式内容。"""
    # 按频道分组，保持顺序
    channels = _group_passed_results(passed_results)

    lines = []
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines.append(f'🕘️更新时间,#genre#')
    lines.append(f'{now_str},邮箱联系')
    lines.append('')

    # 按 demo.txt 的分类结构输出
    try:
        from app import parse_demo_file, load_aliases
        _, name_to_canonical, regex_aliases = load_aliases()
        demo = parse_demo_file()
        for genre, ch_list in demo:
            genre_lines = []
            for ch in ch_list:
                for result in _results_for_channel(ch, channels, name_to_canonical, regex_aliases):
                    genre_lines.append(f'{ch},{result["url"]}')
            if genre_lines:
                lines.append(f'{genre},#genre#')
                lines.extend(genre_lines)
                lines.append('')
    except Exception:
        # fallback: 简单列表
        max_urls = _get_max_urls_per_channel()
        for ch, results in channels.items():
            if max_urls > 0:
                results = results[:max_urls]
            for result in results:
                lines.append(f'{ch},{result["url"]}')

    return '\n'.join(lines)


def _generate_result_m3u(passed_results):
    """从通过的结果动态生成 result.m3u 格式内容。"""
    channels = _group_passed_results(passed_results)

    logo_base = 'https://www.xn--rgv465a.top/tvlogo'
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = ['#EXTM3U x-tvg-url="http://192.168.3.61:8080/epg/epg.gz"']

    # 更新时间条目
    lines.append(
        f'#EXTINF:-1 tvg-id="更新时间" tvg-name="更新时间" '
        f'group-title="🕘️更新时间",{now_str}'
    )
    lines.append('http://localhost/update_time')

    try:
        from app import parse_demo_file, load_aliases
        _, name_to_canonical, regex_aliases = load_aliases()
        demo = parse_demo_file()
        for genre, ch_list in demo:
            for ch in ch_list:
                for result in _results_for_channel(ch, channels, name_to_canonical, regex_aliases):
                    lines.append(
                        f'#EXTINF:-1 tvg-id="{ch}" tvg-name="{ch}" '
                        f'tvg-logo="{logo_base}/{ch}.png" '
                        f'group-title="{genre}",{ch}'
                    )
                    lines.append(result['url'])
    except Exception:
        max_urls = _get_max_urls_per_channel()
        for ch, results in channels.items():
            if max_urls > 0:
                results = results[:max_urls]
            for result in results:
                lines.append(
                    f'#EXTINF:-1 tvg-id="{ch}" tvg-name="{ch}" '
                    f'tvg-logo="{logo_base}/{ch}.png" '
                    f'group-title="默认",{ch}'
                )
                lines.append(result['url'])

    return '\n'.join(lines)


@app.route('/api/download/<fmt>', methods=['GET'])
def api_download(fmt):
    """下载结果文件（从数据库动态生成）。"""
    if fmt not in ('txt', 'm3u'):
        return jsonify({'error': '格式仅支持 txt 或 m3u'}), 400

    passed = get_latest_passed_results()
    if not passed:
        return jsonify({'error': '暂无通过的频道数据'}), 404

    if fmt == 'txt':
        content = _generate_result_txt(passed)
        filename = 'result.txt'
        mimetype = 'text/plain'
    else:
        content = _generate_result_m3u(passed)
        filename = 'result.m3u'
        mimetype = 'application/x-mpegurl'

    # 写入临时文件返回
    import io
    buf = io.BytesIO(content.encode('utf-8'))
    buf.seek(0)
    return send_file(buf, mimetype=mimetype, as_attachment=True, download_name=filename)


# ─────────────── 触发测试 API ───────────────

@app.route('/api/trigger', methods=['POST'])
def api_trigger():
    """触发一次测试运行。"""
    global _test_running, _test_log_seq
    with _test_lock:
        if _test_running:
            return jsonify({'error': '测试正在运行中，请等待完成'}), 409
        _test_running = True

    # 重置进度
    _test_progress.update({
        'running': True,
        'started_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'total': 0, 'processed': 0, 'passed': 0, 'failed': 0,
        'elapsed': 0, 'finished_at': None, 'error': None,
    })
    _test_log_lines.clear()
    _test_log_seq = 0
    _start_time = time.time()
    _run_id = datetime.now().strftime('%Y%m%d_%H%M%S')

    def _on_progress(info):
        """由 filter_and_save_playlist 的 progress_callback 调用。"""
        _test_progress.update({
            'total': info.get('total', 0),
            'processed': info.get('processed', 0),
            'passed': info.get('success', 0),
            'failed': info.get('failed', 0),
            'elapsed': round(time.time() - _start_time, 1),
        })

    def _on_log(msg):
        """由 run_test_cycle 的 log_callback 调用。"""
        global _test_log_seq
        _test_log_seq += 1
        now = datetime.now().strftime('%H:%M:%S')
        _test_log_lines.append({
            'seq': _test_log_seq,
            'time': now,
            'msg': msg,
        })
        # 同时写入数据库，供历史查看
        try:
            from db import insert_log
            insert_log(_run_id, 'INFO', msg)
        except Exception:
            pass

    def _run():
        global _test_running
        try:
            from app import run_test_cycle
            run_test_cycle(progress_callback=_on_progress, log_callback=_on_log)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Web 触发测试失败: {e}")
            _on_log(f"测试异常终止: {e}")
            _test_progress['error'] = str(e)
        finally:
            _test_progress['running'] = False
            _test_progress['finished_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            _test_progress['elapsed'] = round(time.time() - _start_time, 1)
            with _test_lock:
                _test_running = False
            # 确保 SQLite 进度也被清空
            try:
                from db import clear_run_progress
                clear_run_progress()
            except Exception:
                pass

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return jsonify({'ok': True, 'message': '测试已启动'})


@app.route('/api/status', methods=['GET'])
def api_status():
    """获取当前运行状态（精简版）。优先内存，其次 SQLite。"""
    if _test_progress['running']:
        return jsonify({
            'running': True,
            'processed': _test_progress['processed'],
            'total': _test_progress['total'],
            'elapsed': _test_progress['elapsed'],
            'source': 'web',
        })
    from db import get_run_progress
    db_progress = get_run_progress()
    if db_progress and db_progress.get('running'):
        return jsonify({
            'running': True,
            'processed': db_progress.get('processed', 0),
            'total': db_progress.get('total', 0),
            'elapsed': db_progress.get('elapsed', 0),
            'source': db_progress.get('source', 'scheduler'),
        })
    return jsonify({
        'running': False,
        'processed': 0,
        'total': 0,
        'elapsed': 0,
        'source': '',
    })


@app.route('/api/progress', methods=['GET'])
def api_progress():
    """获取实时进度和日志（支持增量拉取）。
    查询参数: after=N  只返回序号 > N 的日志行。
    优先返回 Web 触发的内存数据（含日志），否则查 SQLite（定时任务）。
    """
    after = request.args.get('after', 0, type=int)

    # 优先检查 Web 触发的内存进度
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
            'source': 'web',
        })

    # 检查 SQLite 中的定时任务进度
    from db import get_run_progress
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
        })

    # 没有运行中的测试
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
    })


# ─────────────── 启动 ───────────────

if __name__ == '__main__':
    try:
        port = 58080
        try:
            cfg = load_config()
            port = int(cfg.get('web_port', 58080))
        except Exception:
            pass

        print(f"Web 管理后台已启动: http://localhost:{port}")
        app.run(host='0.0.0.0', port=port, debug=False)
    except OSError as e:
        print(f"\n端口 {port} 被占用，请关闭占用该端口的程序，或在 config.json 中修改 web_port")
        print(f"错误详情: {e}")
        input("\n按回车键退出...")
    except Exception as e:
        import traceback
        print(f"\n启动失败: {e}")
        traceback.print_exc()
        input("\n按回车键退出...")

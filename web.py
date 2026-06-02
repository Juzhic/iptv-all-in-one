"""IPTV 测速管理后台 — Web 服务。"""
import collections
import json
import os
import threading
import time
from datetime import datetime

from flask import Flask, render_template, request, jsonify, send_file
from db import (
    init_db, migrate_from_json,
    get_latest_run, get_latest_passed_results,
    get_run_history, get_run_detail, get_channel_summary,
    get_codec_stats, delete_run,
    get_config_data, set_config_data, DEFAULT_DEMO,
    get_config, save_config as db_save_config,
    get_scheduler_state, update_scheduler_state, clear_scheduler_state,
    now_str,
)
from app import load_config, DEFAULT_CONFIG

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.jinja_env.auto_reload = True
app.jinja_env.cache = None


def _asset_version(filename):
    """用静态文件修改时间生成版本号，避免部署后浏览器继续使用旧资源。"""
    path = os.path.join(app.static_folder, filename.replace('/', os.sep))
    try:
        return str(int(os.path.getmtime(path)))
    except OSError:
        return str(int(time.time()))


@app.context_processor
def inject_asset_version():
    return {'asset_version': _asset_version('js/index.js')}

# 初始化数据库（模块加载时执行，兼容 uWSGI / gunicorn 等 WSGI 服务器）
init_db()
migrate_from_json()
try:
    from db import clear_run_progress
    clear_run_progress()
except Exception:
    pass


@app.after_request
def add_no_cache_headers(response):
    """禁止浏览器和反向代理缓存动态页面/API，避免部署后看到旧页面。"""
    dynamic_response = (
        'text/html' in response.content_type
        or response.content_type.startswith('application/json')
        or request.path.startswith('/api/')
        or request.path.startswith('/static/')
    )
    if dynamic_response:
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0, private'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        response.headers['Surrogate-Control'] = 'no-store'
        response.headers['X-Accel-Expires'] = '0'
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    return response

# 允许通过 Web 编辑的数据 key
ALLOWED_DATA_KEYS = {'alias', 'demo', 'subscribe'}

# 测试运行状态锁
_test_running = False
_test_lock = threading.Lock()
_test_stop_event = threading.Event()
_test_active_token = None

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
    'source': '',
    'last_seq': 0,
}
_test_log_lines = collections.deque(maxlen=200)  # 环形缓冲，最多 200 行日志
_test_log_seq = 0  # 日志序号，用于增量拉取

# 调度器状态
_next_scheduled_run = None  # 下次定时执行时间（datetime 或 None）
_scheduler_running = False  # 调度线程是否存活
_scheduler_thread = None
_scheduler_thread_lock = threading.Lock()
_scheduler_lock_handle = None
_scheduler_owner = f'pid:{os.getpid()}'


def _format_schedule_time(value):
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%d %H:%M:%S')
    return value or None


def _write_scheduler_state(running, next_run=None):
    try:
        update_scheduler_state(
            running=running,
            next_run=_format_schedule_time(next_run),
            owner=_scheduler_owner if running else '',
        )
    except Exception:
        pass


def _acquire_scheduler_lock():
    """跨进程抢占调度器锁，避免 gunicorn/uWSGI 多 worker 重复定时执行。"""
    global _scheduler_lock_handle
    if _scheduler_lock_handle is not None:
        return True

    os.makedirs('output', exist_ok=True)
    lock_handle = open(os.path.join('output', 'scheduler.lock'), 'a+', encoding='utf-8')
    try:
        if os.name == 'nt':
            import msvcrt
            lock_handle.seek(0)
            msvcrt.locking(lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock_handle.close()
        return False

    lock_handle.seek(0)
    lock_handle.truncate()
    lock_handle.write(f'{_scheduler_owner} {now_str()}\n')
    lock_handle.flush()
    _scheduler_lock_handle = lock_handle
    return True


def _release_scheduler_lock():
    global _scheduler_lock_handle
    if _scheduler_lock_handle is None:
        return
    try:
        if os.name == 'nt':
            import msvcrt
            _scheduler_lock_handle.seek(0)
            msvcrt.locking(_scheduler_lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(_scheduler_lock_handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        _scheduler_lock_handle.close()
    finally:
        _scheduler_lock_handle = None


def _ensure_scheduler_started(cfg=None):
    """在当前配置需要定时时启动调度线程；WSGI 导入模式也会生效。"""
    global _scheduler_running, _scheduler_thread
    try:
        cfg = cfg or load_config()
    except Exception:
        return False

    if cfg.get('run_mode', 'once') == 'once':
        return False

    with _scheduler_thread_lock:
        if _scheduler_thread is not None and _scheduler_thread.is_alive():
            return True
        if not _acquire_scheduler_lock():
            return False
        _scheduler_running = True
        _write_scheduler_state(True, _next_scheduled_run)
        _scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True, name='scheduler')
        _scheduler_thread.start()
        return True


def _scheduler_status():
    """返回页面展示用的调度状态，兼容多进程请求落到非调度 worker。"""
    if not _scheduler_running:
        _ensure_scheduler_started()

    next_run_str = _format_schedule_time(_next_scheduled_run)
    scheduler_running = _scheduler_running
    if next_run_str and scheduler_running:
        return scheduler_running, next_run_str

    try:
        state = get_scheduler_state()
    except Exception:
        state = None
    if state and state.get('running'):
        return True, state.get('next_run') or next_run_str
    return scheduler_running, next_run_str


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
    if cfg.get('run_mode', 'once') == 'once':
        try:
            clear_scheduler_state()
        except Exception:
            pass
    else:
        _ensure_scheduler_started(cfg)
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

def _is_run_token_active(run_token):
    """判断指定后台任务是否仍是当前活跃任务。"""
    with _test_lock:
        return _test_running and _test_active_token is run_token


def _start_test_background(trigger_source='web'):
    """启动一次后台测试。返回本次任务 token；已有测试在运行时返回 None。"""
    global _test_running, _test_log_seq, _test_stop_event, _test_active_token
    with _test_lock:
        if _test_running:
            return None
        run_token = object()
        stop_event = threading.Event()
        _test_running = True
        _test_stop_event = stop_event
        _test_active_token = run_token

    # 重置进度
    _test_progress.update({
        'running': True,
        'started_at': now_str(),
        'total': 0, 'processed': 0, 'passed': 0, 'failed': 0,
        'elapsed': 0, 'finished_at': None, 'error': None,
        'source': trigger_source,
        'last_seq': 0,
    })
    _test_log_lines.clear()
    _test_log_seq = 0
    _start_time = time.time()
    _run_id = now_str().replace('-', '').replace(':', '').replace(' ', '_')

    def _on_progress(info):
        _test_progress.update({
            'total': info.get('total', 0),
            'processed': info.get('processed', 0),
            'passed': info.get('success', 0),
            'failed': info.get('failed', 0),
            'elapsed': round(time.time() - _start_time, 1),
            'last_seq': _test_log_seq,
        })

    def _on_log(msg):
        global _test_log_seq
        _test_log_seq += 1
        now = datetime.now().strftime('%H:%M:%S')
        _test_log_lines.append({
            'seq': _test_log_seq,
            'time': now,
            'msg': msg,
        })
        try:
            from db import insert_log
            insert_log(_run_id, 'INFO', msg)
        except Exception:
            pass

    def _run():
        global _test_running, _test_active_token
        try:
            from app import run_test_cycle
            run_test_cycle(
                progress_callback=_on_progress,
                log_callback=_on_log,
                stop_event=stop_event,
                progress_source=trigger_source,
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"测试失败: {e}")
            _on_log(f"测试异常终止: {e}")
            _test_progress['error'] = str(e)
        finally:
            with _test_lock:
                is_current_run = _test_active_token is run_token
            if is_current_run:
                _on_log("后台测试任务已结束")
                with _test_lock:
                    total = _test_progress.get('total', 0)
                    processed = _test_progress.get('processed', 0)
                    if total and processed < total and not _test_progress.get('error'):
                        _test_progress['processed'] = total
                        _test_progress['failed'] = max(0, total - _test_progress.get('passed', 0))
                    _test_progress['running'] = False
                    _test_progress['finished_at'] = now_str()
                    _test_progress['elapsed'] = round(time.time() - _start_time, 1)
                    _test_progress['last_seq'] = _test_log_seq
                    _test_running = False
                    _test_active_token = None
            if is_current_run:
                try:
                    from db import clear_run_progress
                    clear_run_progress()
                except Exception:
                    pass

    t = threading.Thread(target=_run, daemon=True, name=f'test-{trigger_source}')
    t.start()
    return run_token


@app.route('/api/stop', methods=['POST'])
def api_stop():
    """请求终止当前测试，实际清理由后台线程退出时完成。"""
    msg = '已请求终止当前测试'
    with _test_lock:
        if not _test_running:
            return jsonify({'error': '当前没有正在运行的测试'}), 409
        _test_stop_event.set()
        _test_progress['error'] = msg
    return jsonify({'ok': True, 'message': msg})


def _scheduler_loop():
    """后台调度循环：按配置的 run_mode 定时触发测试。"""
    global _next_scheduled_run, _scheduler_running, _scheduler_thread
    _scheduler_running = True
    _write_scheduler_state(True, _next_scheduled_run)
    # 导入 app 模块的调度函数
    from app import _next_run_datetime

    try:
        while True:
            cfg = load_config()
            run_mode = cfg.get('run_mode', 'once')
            if run_mode == 'once':
                _next_scheduled_run = None
                _write_scheduler_state(False, None)
                break  # 一次性模式，调度线程退出

            next_run = _next_run_datetime(run_mode, cfg.get('run_times', []), cfg.get('run_interval_minutes', 0))
            if next_run is None:
                _next_scheduled_run = None
                _write_scheduler_state(True, None)
                time.sleep(60)  # 配置无效，等 1 分钟后重试
                continue

            _next_scheduled_run = next_run
            _write_scheduler_state(True, next_run)
            wait_sec = (next_run - datetime.now()).total_seconds()
            if wait_sec > 0:
                # 分段 sleep，每 30 秒检查一次配置是否变更
                while wait_sec > 0:
                    time.sleep(min(wait_sec, 30))
                    wait_sec = (next_run - datetime.now()).total_seconds()
                    # 如果配置变更导致下次时间不同，重新计算
                    current_cfg = load_config()
                    current_mode = current_cfg.get('run_mode', 'once')
                    if current_mode != run_mode:
                        break  # 模式变了，跳出内层循环重新计算
                else:
                    # wait_sec <= 0，到达执行时间
                    pass

                # 检查是否因配置变更跳出
                current_cfg = load_config()
                if current_cfg.get('run_mode', 'once') != run_mode:
                    continue  # 模式变了，重新开始循环

            print(f"\n{'#' * 60}")
            print(f"定时任务触发：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'#' * 60}")
            run_token = _start_test_background(trigger_source='scheduler')
            if run_token is None:
                print("已有测试正在运行，本次定时任务跳过，等待下一个设定时间点")
                continue

            # interval 模式：只等待本次由调度器启动的任务结束；手动任务不参与重新计时
            if run_mode == 'interval':
                while _is_run_token_active(run_token):
                    time.sleep(5)
                continue
            # times 模式：循环顶部会自动计算下一个时间点
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"调度器异常退出: {e}")
    finally:
        _scheduler_running = False
        _next_scheduled_run = None
        _scheduler_thread = None
        try:
            clear_scheduler_state()
        except Exception:
            pass
        _release_scheduler_lock()


@app.route('/api/trigger', methods=['POST'])
def api_trigger():
    """触发一次测试运行。"""
    if _start_test_background(trigger_source='web') is not None:
        return jsonify({'ok': True, 'message': '测试已启动'})
    return jsonify({'error': '测试正在运行中，请等待完成'}), 409


@app.route('/api/status', methods=['GET'])
def api_status():
    """获取当前运行状态（精简版）。优先内存，其次 SQLite。"""
    scheduler_running, next_run_str = _scheduler_status()
    if _test_progress['running']:
        return jsonify({
            'running': True,
            'processed': _test_progress['processed'],
            'total': _test_progress['total'],
            'elapsed': _test_progress['elapsed'],
            'source': _test_progress.get('source', 'web'),
            'next_scheduled_run': next_run_str,
            'scheduler_running': scheduler_running,
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
            'next_scheduled_run': next_run_str,
            'scheduler_running': scheduler_running,
        })
    return jsonify({
        'running': False,
        'processed': 0,
        'total': 0,
        'elapsed': 0,
        'source': '',
        'next_scheduled_run': next_run_str,
        'scheduler_running': scheduler_running,
    })


@app.route('/api/progress', methods=['GET'])
def api_progress():
    """获取实时进度和日志（支持增量拉取）。
    查询参数: after=N  只返回序号 > N 的日志行。
    优先返回 Web 触发的内存数据（含日志），否则查 SQLite（定时任务）。
    """
    after = request.args.get('after', 0, type=int)
    scheduler_running, next_run_str = _scheduler_status()
    sched_info = {
        'next_scheduled_run': next_run_str,
        'scheduler_running': scheduler_running,
    }

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
            'source': _test_progress.get('source', 'web'),
            **sched_info,
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
            **sched_info,
        })

    if _test_progress.get('finished_at'):
        new_lines = [l for l in _test_log_lines if l['seq'] > after]
        return jsonify({
            'running': False,
            'started_at': _test_progress.get('started_at'),
            'total': _test_progress.get('total', 0),
            'processed': _test_progress.get('processed', 0),
            'passed': _test_progress.get('passed', 0),
            'failed': _test_progress.get('failed', 0),
            'elapsed': _test_progress.get('elapsed', 0),
            'finished_at': _test_progress.get('finished_at'),
            'error': _test_progress.get('error'),
            'lines': new_lines,
            'last_seq': _test_log_seq,
            'source': _test_progress.get('source', ''),
            **sched_info,
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
        **sched_info,
    })


def _start_scheduler_from_config():
    """模块导入时也按配置启动调度器，兼容 WSGI/宝塔部署。"""
    try:
        cfg = load_config()
    except Exception:
        return
    if cfg.get('run_mode', 'once') != 'once':
        _ensure_scheduler_started(cfg)


_start_scheduler_from_config()


# ─────────────── 启动 ───────────────

if __name__ == '__main__':
    try:
        host = '0.0.0.0'
        port = 58080
        try:
            cfg = load_config()
        except Exception:
            cfg = DEFAULT_CONFIG
            pass

        # 启动定时调度线程
        run_mode = cfg.get('run_mode', 'once') if cfg else 'once'
        if run_mode != 'once':
            _ensure_scheduler_started(cfg)
            label = f"指定时间 {cfg.get('run_times', [])}" if run_mode == 'times' else f"每 {cfg.get('run_interval_minutes', 60)} 分钟"
            print(f"定时调度已启动：{label}")
        else:
            print("运行模式：once（仅手动触发）")

        print(f"Web 管理后台已启动: http://localhost:{port}")
        app.run(host=host, port=port, debug=False)
    except OSError as e:
        print(f"\n端口 {port} 启动失败: {e}")
        print("Web 服务只允许绑定 58080，请先结束占用 58080 的旧进程后再重启。")
        input("\n按回车键退出...")
    except Exception as e:
        import traceback
        print(f"\n启动失败: {e}")
        traceback.print_exc()
        input("\n按回车键退出...")

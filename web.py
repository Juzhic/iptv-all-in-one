"""IPTV 测速管理后台 — Web 服务。"""
import collections
import hmac
import importlib.util
import json
import os
import pkgutil
import sys
import logging
import subprocess
import threading
import time
from datetime import datetime

# Python 3.14 移除了 pkgutil.get_loader，当前 Flask 仍会调用它。
if not hasattr(pkgutil, 'get_loader'):
    def _compat_get_loader(module_or_name):
        name = module_or_name if isinstance(module_or_name, str) else getattr(module_or_name, '__name__', None)
        if not name:
            return None
        spec = importlib.util.find_spec(name)
        return spec.loader if spec else None

    pkgutil.get_loader = _compat_get_loader

from flask import Flask, request, jsonify, send_file, send_from_directory, Response
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
from test_engine import load_config, DEFAULT_CONFIG, resolve_output_update_time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, root_path=BASE_DIR, instance_path=BASE_DIR)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

DIST_DIR = os.path.join(BASE_DIR, 'dist')
FRONTEND_DIR = os.path.join(BASE_DIR, 'frontend')
logger = logging.getLogger(__name__)


def _safe_mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0


def _iter_frontend_watch_files():
    """返回需要触发前端重构的源码和配置文件。"""
    for name in ('index.html', 'vite.config.js', 'package.json', 'package-lock.json'):
        path = os.path.join(FRONTEND_DIR, name)
        if os.path.exists(path):
            yield path

    src_dir = os.path.join(FRONTEND_DIR, 'src')
    if not os.path.isdir(src_dir):
        return

    for root, dirs, files in os.walk(src_dir):
        for filename in files:
            yield os.path.join(root, filename)


def _frontend_deps_need_install():
    """package.json / package-lock.json 更新后，自动补 npm install。"""
    pkg = os.path.join(FRONTEND_DIR, 'package.json')
    if not os.path.exists(pkg):
        return False

    node_modules_dir = os.path.join(FRONTEND_DIR, 'node_modules')
    if not os.path.isdir(node_modules_dir):
        return True

    manifest_mtime = max(
        _safe_mtime(pkg),
        _safe_mtime(os.path.join(FRONTEND_DIR, 'package-lock.json')),
    )
    install_stamp = os.path.join(node_modules_dir, '.package-lock.json')
    return manifest_mtime > _safe_mtime(install_stamp)


def _ensure_frontend():
    """检查 dist/ 是否存在且为最新；缺失或过期时自动执行 npm run build。"""
    index_html = os.path.join(DIST_DIR, 'index.html')
    if not os.path.exists(index_html):
        # dist 不存在，尝试构建
        pkg = os.path.join(FRONTEND_DIR, 'package.json')
        if not os.path.exists(pkg):
            return  # 无前端源码，跳过
        print('[前端] dist/ 不存在，正在自动构建...')
        _run_frontend_build()
        return

    if _frontend_deps_need_install():
        print('[前端] 检测到依赖清单变更，正在重新安装依赖并构建...')
        _run_frontend_build()
        return

    # dist 存在，检查源码是否有更新
    try:
        dist_mtime = os.path.getmtime(index_html)
        for path in _iter_frontend_watch_files():
            if _safe_mtime(path) > dist_mtime:
                print(f'[前端] 检测到前端文件更新 ({os.path.basename(path)})，正在重新构建...')
                _run_frontend_build()
                return
    except OSError:
        pass


def _run_frontend_build():
    """在 frontend/ 目录执行 npm run build。"""
    pkg = os.path.join(FRONTEND_DIR, 'package.json')
    if not os.path.exists(pkg):
        return

    if _frontend_deps_need_install():
        print('[前端] 正在安装依赖 (npm install)...')
        install_result = subprocess.run(
            ['cmd', '/c', 'npm install --production=false'],
            cwd=FRONTEND_DIR,
            shell=False,
            capture_output=True,
            check=False,
        )
        if install_result.returncode != 0:
            stderr = install_result.stderr.decode('utf-8', errors='replace')[-500:] if install_result.stderr else ''
            print(f'[前端] 依赖安装失败: {stderr}')
            return

    print('[前端] 正在构建 (npm run build)...')
    result = subprocess.run(
        ['cmd', '/c', 'npm run build'],
        cwd=FRONTEND_DIR,
        shell=False,
        capture_output=True,
    )
    # 打印构建输出（过滤关键行）
    if result.stdout:
        for line in result.stdout.decode('utf-8', errors='replace').splitlines():
            line = line.strip()
            if line and ('built in' in line or '.html' in line or '.js' in line or '.css' in line or 'error' in line.lower()):
                # 移除 ANSI 转义码和特殊 Unicode 字符，避免 GBK 终端报错
                import re as _re
                clean = _re.sub(r'\x1b\[[0-9;]*m', '', line)
                clean = clean.replace('✓', '[OK]').replace('✗', '[X]')
                try:
                    print(f'[前端]   {clean}')
                except UnicodeEncodeError:
                    print(f'[前端]   {clean.encode("utf-8", errors="replace").decode("ascii", errors="replace")}')
    if result.returncode == 0:
        print('[前端] 构建完成')
    else:
        stderr = result.stderr.decode('utf-8', errors='replace')[-500:] if result.stderr else ''
        print(f'[前端] 构建失败: {stderr}')


def _prepare_frontend_on_startup():
    """启动 Web 服务前预构建前端，避免首个请求时才发现 dist 缺失。"""
    _ensure_frontend()
    index_html = os.path.join(DIST_DIR, 'index.html')
    if not os.path.exists(index_html):
        raise RuntimeError('前端构建失败或 dist/index.html 不存在，请检查 frontend 构建日志')
BASIC_AUTH_CONFIG_FILE = os.path.join(BASE_DIR, 'basic_auth.json')
BASIC_AUTH_DEFAULT_CONFIG = {
    'username': 'admin',
    'password': 'admin',
    'realm': 'IPTV Test',
}
BASIC_AUTH_EXEMPT_PATHS = {'/api/download/txt', '/api/download/m3u'}


def _load_basic_auth_config():
    config = dict(BASIC_AUTH_DEFAULT_CONFIG)
    try:
        with open(BASIC_AUTH_CONFIG_FILE, 'r', encoding='utf-8') as f:
            loaded = json.load(f)
    except FileNotFoundError:
        return config
    except (OSError, ValueError):
        return config

    if not isinstance(loaded, dict):
        return config

    for key in config:
        value = loaded.get(key)
        if value is not None:
            value = str(value)
            if value:
                config[key] = value
    return config


BASIC_AUTH_CONFIG = _load_basic_auth_config()
BASIC_AUTH_USER = BASIC_AUTH_CONFIG['username']
BASIC_AUTH_PASSWORD = BASIC_AUTH_CONFIG['password']
BASIC_AUTH_REALM = BASIC_AUTH_CONFIG['realm']


def _basic_auth_challenge():
    response = Response('Authentication required', 401)
    response.headers['WWW-Authenticate'] = f'Basic realm="{BASIC_AUTH_REALM}"'
    return response


def _basic_auth_valid(auth):
    if not auth or (auth.type or '').lower() != 'basic':
        return False
    username = auth.username or ''
    password = auth.password or ''
    return (
        hmac.compare_digest(username.encode('utf-8'), BASIC_AUTH_USER.encode('utf-8'))
        and hmac.compare_digest(password.encode('utf-8'), BASIC_AUTH_PASSWORD.encode('utf-8'))
    )


@app.before_request
def require_basic_auth():
    """保护后台页面和 API；TXT/M3U 下载接口保持免登录，便于订阅客户端拉取。"""
    if request.path in BASIC_AUTH_EXEMPT_PATHS:
        return None
    if _basic_auth_valid(request.authorization):
        return None
    return _basic_auth_challenge()


def _finite_number_or_none(value):
    """把外部 API 的数字字段规整成 JSON number；无效值返回 None。"""
    if value is None or value == '':
        return None
    try:
        num = float(str(value).replace(',', '').strip())
    except (TypeError, ValueError):
        return None
    if num != num or num in (float('inf'), float('-inf')):
        return None
    return int(num) if num.is_integer() else num



# 初始化数据库（模块加载时执行，兼容 uWSGI / gunicorn 等 WSGI 服务器）
init_db()
migrate_from_json()
try:
    from db import clear_run_progress
    clear_run_progress()
except Exception:
    pass

# 检查前端是否需要构建（dist/ 不存在或源码更新时自动 npm run build）
_ensure_frontend()

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
    """服务 Vue SPA 入口文件。"""
    spa_path = os.path.join(DIST_DIR, 'index.html')
    if os.path.exists(spa_path):
        return send_file(spa_path)
    _ensure_frontend()
    if os.path.exists(spa_path):
        return send_file(spa_path)
    return '前端未构建，请先执行: cd frontend && npm run build', 500


@app.route('/static/dist/<path:filename>')
def serve_spa_assets(filename):
    """服务 Vue SPA 构建产物（JS/CSS/图片等）。"""
    if not os.path.isdir(DIST_DIR):
        _ensure_frontend()
    return send_from_directory(DIST_DIR, filename)


@app.route('/api/initial')
def api_initial():
    """为 Vue SPA 提供初始数据（替代 Jinja2 服务端渲染）。"""
    latest = get_latest_run()
    runs = get_run_history()
    channel_summary = {}
    codec_stats = {}
    if latest and latest.get('results'):
        channel_summary = get_channel_summary(latest['run_id'])
        codec_stats = get_codec_stats(latest['run_id'])
    return jsonify({
        'latest': latest,
        'runs': runs,
        'channel_summary': channel_summary,
        'codec_stats': codec_stats,
    })


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
    limit = request.args.get('limit', 0, type=int)
    from db import get_run_logs
    payload = get_run_logs(run_id, limit=limit if limit and limit > 0 else None)
    return jsonify(payload)


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
        from alias import match_channel_name
        canonical = match_channel_name(ch, name_to_canonical, regex_aliases)
        if canonical and canonical != ch:
            results = channels.get(canonical, [])
    max_urls = _get_max_urls_per_channel()
    if max_urls > 0:
        return results[:max_urls]
    return results

def _generate_result_txt(passed_results, fallback_update_time=None):
    """从通过的结果动态生成 result.txt 格式内容。"""
    # 按频道分组，保持顺序
    channels = _group_passed_results(passed_results)

    selected_results = []
    body_lines = []

    # 按 demo.txt 的分类结构输出
    try:
        from test_engine import parse_demo_file
        from alias import load_aliases
        _, name_to_canonical, regex_aliases = load_aliases()
        demo = parse_demo_file()
        for genre, ch_list in demo:
            genre_lines = []
            genre_results = []
            for ch in ch_list:
                for result in _results_for_channel(ch, channels, name_to_canonical, regex_aliases):
                    genre_lines.append(f'{ch},{result["url"]}')
                    genre_results.append(result)
            if genre_lines:
                body_lines.append(f'{genre},#genre#')
                body_lines.extend(genre_lines)
                body_lines.append('')
                selected_results.extend(genre_results)
    except Exception:
        # fallback: 简单列表
        max_urls = _get_max_urls_per_channel()
        for ch, results in channels.items():
            if max_urls > 0:
                results = results[:max_urls]
            for result in results:
                body_lines.append(f'{ch},{result["url"]}')
                selected_results.append(result)

    update_time_str = resolve_output_update_time(selected_results, fallback_update_time)
    lines = [
        '🕘️更新时间,#genre#',
        f'{update_time_str},邮箱联系',
        '',
    ]
    lines.extend(body_lines)
    return '\n'.join(lines)


def _generate_result_m3u(passed_results, fallback_update_time=None):
    """从通过的结果动态生成 result.m3u 格式内容。"""
    channels = _group_passed_results(passed_results)

    logo_base = 'https://www.xn--rgv465a.top/tvlogo'
    selected_results = []
    body_lines = []

    try:
        from test_engine import parse_demo_file
        from alias import load_aliases
        _, name_to_canonical, regex_aliases = load_aliases()
        demo = parse_demo_file()
        for genre, ch_list in demo:
            for ch in ch_list:
                for result in _results_for_channel(ch, channels, name_to_canonical, regex_aliases):
                    body_lines.append(
                        f'#EXTINF:-1 tvg-id="{ch}" tvg-name="{ch}" '
                        f'tvg-logo="{logo_base}/{ch}.png" '
                        f'group-title="{genre}",{ch}'
                    )
                    body_lines.append(result['url'])
                    selected_results.append(result)
    except Exception:
        max_urls = _get_max_urls_per_channel()
        for ch, results in channels.items():
            if max_urls > 0:
                results = results[:max_urls]
            for result in results:
                body_lines.append(
                    f'#EXTINF:-1 tvg-id="{ch}" tvg-name="{ch}" '
                    f'tvg-logo="{logo_base}/{ch}.png" '
                    f'group-title="默认",{ch}'
                )
                body_lines.append(result['url'])
                selected_results.append(result)

    update_time_str = resolve_output_update_time(selected_results, fallback_update_time)
    lines = ['#EXTM3U x-tvg-url="http://192.168.3.61:8080/epg/epg.gz"']
    lines.append(
        f'#EXTINF:-1 tvg-id="更新时间" tvg-name="更新时间" '
        f'group-title="🕘️更新时间",{update_time_str}'
    )
    lines.append('http://localhost/update_time')
    lines.extend(body_lines)
    return '\n'.join(lines)


@app.route('/api/download/<fmt>', methods=['GET'])
def api_download(fmt):
    """下载结果文件（从数据库动态生成）。"""
    if fmt not in ('txt', 'm3u'):
        return jsonify({'error': '格式仅支持 txt 或 m3u'}), 400

    latest_run = get_latest_run()
    passed = get_latest_passed_results()
    if not passed:
        return jsonify({'error': '暂无通过的频道数据'}), 404
    fallback_update_time = (latest_run or {}).get('finished_at')

    if fmt == 'txt':
        content = _generate_result_txt(passed, fallback_update_time)
        filename = 'result.txt'
        mimetype = 'text/plain'
    else:
        content = _generate_result_m3u(passed, fallback_update_time)
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


def _start_test_background(trigger_source='web', test_list=None, scan_id=None):
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
            from test_engine import run_test_cycle
            run_test_cycle(
                progress_callback=_on_progress,
                log_callback=_on_log,
                stop_event=stop_event,
                progress_source=trigger_source,
                test_list=test_list,
                scan_id=scan_id,
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
    from test_engine import _next_run_datetime

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


# ─────────────── 扫描模块 API ───────────────

def _get_scanner():
    """获取 scanner_integration 模块（延迟导入，避免未安装 aiohttp 时报错）。"""
    try:
        import scanner_integration as scanner
        return scanner
    except ImportError as e:
        return None


def _ensure_scan_bridge():
    """确保扫描桥接层已初始化。"""
    scanner = _get_scanner()
    if scanner is None:
        return None, jsonify({'error': '扫描模块依赖未安装，请先安装 aiohttp: pip install aiohttp'}), 503
    if scanner.bridge._loop is None or not scanner.bridge._loop.is_running():
        scanner.init_bridge()
    return scanner, None, None


@app.route('/api/scan/trigger', methods=['POST'])
def api_scan_trigger():
    """启动一次扫描。"""
    scanner, err, code = _ensure_scan_bridge()
    if err:
        return err, code
    data = request.get_json(silent=True) or {}
    result = scanner.trigger_scan(
        platforms=data.get('platforms'),
        provinces=data.get('provinces')
    )
    if 'error' in result:
        return jsonify(result), 409
    return jsonify({'ok': True, 'message': '扫描已启动'})


@app.route('/api/scan/stop', methods=['POST'])
def api_scan_stop():
    """请求停止扫描。"""
    scanner, err, code = _ensure_scan_bridge()
    if err:
        return err, code
    result = scanner.trigger_stop()
    return jsonify(result)


@app.route('/api/scan/force-clear', methods=['POST'])
def api_scan_force_clear():
    """强制清除卡死的扫描状态。"""
    scanner = _get_scanner()
    if scanner is None:
        db.clear_scan_progress()
        return jsonify({'ok': True, 'message': '扫描状态已清除'})
    result = scanner.force_clear_scan()
    return jsonify(result)


@app.route('/api/scan/health', methods=['POST'])
def api_scan_health():
    """触发健康检查。"""
    scanner, err, code = _ensure_scan_bridge()
    if err:
        return err, code
    result = scanner.trigger_health_check()
    if 'error' in result:
        return jsonify(result), 409
    return jsonify({'ok': True, 'message': '健康检查已启动'})


@app.route('/api/scan/status', methods=['GET'])
def api_scan_status():
    """获取扫描实时进度。"""
    scanner = _get_scanner()
    if scanner is None:
        return jsonify({'running': False, 'phase': 'idle', 'message': '扫描模块未安装'})
    status = scanner.get_scan_status()
    return jsonify(status)


@app.route('/api/scan/results', methods=['GET'])
def api_scan_results():
    """分页查询扫描结果。"""
    scanner = _get_scanner()
    if scanner is None:
        return jsonify({'total': 0, 'items': []})
    scan_id = request.args.get('scan_id')
    page = int(request.args.get('page', 1))
    size = int(request.args.get('size', 50))
    category = request.args.get('category')
    province = request.args.get('province')
    search = request.args.get('search')
    total, items = scanner.get_scan_results(
        scan_id=scan_id, page=page, size=size,
        category=category, province=province, search=search
    )
    return jsonify({'total': total, 'items': items, 'page': page, 'size': size})


@app.route('/api/scan/latest', methods=['GET'])
def api_scan_latest():
    """获取最新扫描记录。"""
    scanner = _get_scanner()
    if scanner is None:
        return jsonify(None)
    return jsonify(scanner.get_latest_scan())


@app.route('/api/scan/history', methods=['GET'])
def api_scan_history():
    """获取扫描历史。"""
    scanner = _get_scanner()
    if scanner is None:
        return jsonify([])
    limit = int(request.args.get('limit', 50))
    return jsonify(scanner.get_scan_history(limit=limit))


@app.route('/api/scan/run/<scan_id>', methods=['DELETE'])
def api_scan_delete(scan_id):
    """删除扫描记录。"""
    scanner = _get_scanner()
    if scanner is None:
        return jsonify({'error': '扫描模块未安装'}), 503
    scanner.delete_scan(scan_id)
    return jsonify({'ok': True})


@app.route('/api/scan/feed-to-test', methods=['POST'])
def api_scan_feed_to_test():
    """将扫描结果送入测速流水线。"""
    scanner, err, code = _ensure_scan_bridge()
    if err:
        return err, code

    data = request.get_json(silent=True) or {}
    scan_id = data.get('scan_id')
    channel_names = data.get('channel_names')  # None = 全部

    if not scan_id:
        return jsonify({'error': '请指定 scan_id'}), 400

    test_list, error = scanner.feed_scan_to_test(scan_id, channel_names)
    if error:
        return jsonify({'error': error}), 400

    if not test_list:
        return jsonify({'error': '没有可测速的频道'}), 400

    # 标记这些扫描结果已参与测速
    from db import mark_scan_results_tested
    urls = [url for _, url in test_list]
    run_id = now_str().replace('-', '').replace(':', '').replace(' ', '_')
    mark_scan_results_tested(scan_id, urls, run_id)

    # 启动测速
    token = _start_test_background(trigger_source='scan', test_list=test_list, scan_id=scan_id)
    if token is not None:
        return jsonify({
            'ok': True,
            'message': f'已将 {len(test_list)} 个频道地址送入测速',
            'run_id': run_id,
            'count': len(test_list)
        })
    return jsonify({'error': '测试正在运行中，请等待完成'}), 409


@app.route('/api/scan/config', methods=['GET'])
def api_scan_config_get():
    """读取扫描配置（始终从数据库读取，不依赖 bridge）。"""
    try:
        from scanner_integration.config_bridge import get_scan_config
        cfg = get_scan_config()
        return jsonify(cfg)
    except Exception:
        from scanner_integration.config_bridge import DEFAULT_SCAN_CONFIG
        return jsonify(DEFAULT_SCAN_CONFIG)


@app.route('/api/scan/config', methods=['POST'])
def api_scan_config_set():
    """保存扫描配置（不依赖 bridge，直接写数据库）。"""
    try:
        from scanner_integration.config_bridge import save_scan_config, get_scan_config
        from scanner_integration.key_manager import init_key_manager
        data = request.get_json(silent=True) or {}
        save_scan_config(data)
        init_key_manager()
        cfg = get_scan_config()
        return jsonify({'ok': True, 'config': cfg})
    except Exception as e:
        return jsonify({'error': f'保存失败: {e}'}), 500


@app.route('/api/scan/keys', methods=['GET'])
def api_scan_keys_list():
    """列出所有平台的 API Key（含积分信息）。"""
    try:
        from scanner_integration.key_manager import KeyManager, init_key_manager
        from scanner_integration.config_bridge import get_scan_config
        init_key_manager()
        km = KeyManager.instance()
        cfg = get_scan_config()
        credits_info = {}
        # Quake 积分
        try:
            import asyncio
            from scanner_integration.key_manager import check_all_quake_credits
            credits_info['quake'] = asyncio.run(check_all_quake_credits())
        except Exception as e:
            print(f"[Credits] Quake 积分查询失败: {e}")
            credits_info['quake'] = []
        # Hunter points（openApi 接口，使用 api-key 参数）
        try:
            import asyncio
            from scanner_integration.key_manager import check_all_hunter_credits
            credits_info['hunter'] = asyncio.run(check_all_hunter_credits())
        except Exception as e:
            print(f"[Credits] Hunter 积分查询失败: {e}")
            credits_info['hunter'] = []
        # DayDayMap points（scan API 接口，使用 api-key 头）
        try:
            import asyncio
            from scanner_integration.key_manager import check_all_daydaymap_credits
            credits_info['daydaymap'] = asyncio.run(check_all_daydaymap_credits())
        except Exception as e:
            print(f"[Credits] DayDayMap 积分查询失败: {e}")
            credits_info['daydaymap'] = []
        print(f"[Credits] results: hunter={credits_info.get('hunter')}, daydaymap={credits_info.get('daydaymap')}")
        result = []
        for platform in ('quake', 'hunter', 'daydaymap'):
            keys = km.get_all_keys(platform)
            platform_credits = credits_info.get(platform, [])
            credit_map = {c['key_suffix']: c for c in platform_credits}
            for key in keys:
                suffix = f"...{key[-6:]}"
                ci = credit_map.get(suffix, {})
                result.append({
                    'platform': platform,
                    'key': key,
                    'key_suffix': suffix,
                    'credit': _finite_number_or_none(ci.get('credit')),
                    'role': ci.get('role', ''),
                    'role_limit': _finite_number_or_none(ci.get('role_limit')),
                    'error': ci.get('error', ''),
                })
        return jsonify({'ok': True, 'keys': result})
    except Exception as e:
        return jsonify({'error': str(e)})


@app.route('/api/scan/keys', methods=['POST'])
def api_scan_keys_add():
    """添加一个 API Key。"""
    try:
        from scanner_integration.config_bridge import get_scan_config, save_scan_config
        from scanner_integration.key_manager import KeyManager, init_key_manager
        data = request.get_json(silent=True) or {}
        platform = data.get('platform', '').strip()
        key = data.get('key', '').strip()
        if not platform or not key:
            return jsonify({'error': '平台和 Key 不能为空'}), 400
        if platform not in ('quake', 'hunter', 'daydaymap'):
            return jsonify({'error': '不支持的平台'}), 400

        cfg = get_scan_config()
        keys_list = cfg.get(f'{platform}_api_keys', [])
        if not isinstance(keys_list, list):
            keys_list = []
        if key in keys_list:
            return jsonify({'error': 'Key 已存在'}), 400
        keys_list.append(key)
        cfg[f'{platform}_api_keys'] = keys_list
        save_scan_config(cfg)
        init_key_manager()
        return jsonify({'ok': True, 'message': f'{platform} Key 已添加'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/scan/keys', methods=['DELETE'])
def api_scan_keys_delete():
    """删除一个 API Key。"""
    try:
        from scanner_integration.config_bridge import get_scan_config, save_scan_config
        from scanner_integration.key_manager import KeyManager, init_key_manager
        data = request.get_json(silent=True) or {}
        platform = data.get('platform', '').strip()
        key = data.get('key', '').strip()
        if not platform or not key:
            return jsonify({'error': '平台和 Key 不能为空'}), 400

        cfg = get_scan_config()
        keys_list = cfg.get(f'{platform}_api_keys', [])
        if not isinstance(keys_list, list):
            keys_list = []
        if key in keys_list:
            keys_list.remove(key)
        cfg[f'{platform}_api_keys'] = keys_list
        # 兼容：同步更新旧格式
        if len(keys_list) == 1:
            cfg[f'{platform}_api_key'] = keys_list[0]
        elif len(keys_list) == 0:
            cfg[f'{platform}_api_key'] = ''
        save_scan_config(cfg)
        init_key_manager()
        return jsonify({'ok': True, 'message': 'Key 已删除'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/scan/keys', methods=['PUT'])
def api_scan_keys_update():
    """更新一个 API Key（替换旧值）。"""
    try:
        from scanner_integration.config_bridge import get_scan_config, save_scan_config
        from scanner_integration.key_manager import init_key_manager
        data = request.get_json(silent=True) or {}
        platform = data.get('platform', '').strip()
        old_key = data.get('old_key', '').strip()
        new_key = data.get('new_key', '').strip()
        if not platform or not old_key or not new_key:
            return jsonify({'error': '参数不完整'}), 400
        if old_key == new_key:
            return jsonify({'ok': True, 'message': 'Key 未变更'})

        cfg = get_scan_config()
        keys_list = cfg.get(f'{platform}_api_keys', [])
        if not isinstance(keys_list, list):
            keys_list = []
        if old_key not in keys_list:
            return jsonify({'error': '原 Key 不存在'}), 400
        if new_key in keys_list:
            return jsonify({'error': '新 Key 已存在'}), 400
        idx = keys_list.index(old_key)
        keys_list[idx] = new_key
        cfg[f'{platform}_api_keys'] = keys_list
        if len(keys_list) == 1:
            cfg[f'{platform}_api_key'] = keys_list[0]
        save_scan_config(cfg)
        init_key_manager()
        return jsonify({'ok': True, 'message': 'Key 已更新'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/scan/quake-credits', methods=['GET'])
def api_scan_quake_credits():
    """查询所有 Quake key 的积分。"""
    try:
        import asyncio
        from scanner_integration.key_manager import check_all_quake_credits, init_key_manager
        init_key_manager()
        results = asyncio.run(check_all_quake_credits())
        return jsonify({'ok': True, 'keys': results})
    except Exception as e:
        return jsonify({'error': f'查询失败: {e}'})


@app.route('/api/scan/stats', methods=['GET'])
def api_scan_stats():
    """获取扫描结果统计。"""
    scanner = _get_scanner()
    if scanner is None:
        return jsonify({'by_category': {}, 'by_province': {}})
    scan_id = request.args.get('scan_id')
    return jsonify(scanner.get_scan_stats(scan_id=scan_id))


# ─────────────── 启动 ───────────────

if __name__ == '__main__':
    try:
        host = '0.0.0.0'
        port = 58080
        dev_mode = '--dev' in sys.argv

        _prepare_frontend_on_startup()

        try:
            cfg = load_config()
        except Exception:
            cfg = DEFAULT_CONFIG

        # 启动定时调度线程
        run_mode = cfg.get('run_mode', 'once') if cfg else 'once'
        if run_mode != 'once':
            _ensure_scheduler_started(cfg)
            label = f"指定时间 {cfg.get('run_times', [])}" if run_mode == 'times' else f"每 {cfg.get('run_interval_minutes', 60)} 分钟"
            print(f"定时调度已启动：{label}")
        else:
            print("运行模式：once（仅手动触发）")

        if dev_mode:
            # 开发模式：启动 Vite 开发服务器（HMR 热更新）
            frontend_dir = os.path.join(BASE_DIR, 'frontend')
            if os.path.exists(os.path.join(frontend_dir, 'package.json')):
                print("开发模式：正在启动 Vite 开发服务器...")
                subprocess.Popen(
                    ['cmd', '/c', 'npm run dev'],
                    cwd=frontend_dir,
                    creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == 'win32' else 0,
                )
                print("Vite 开发服务器: http://localhost:3000（API 代理到 Flask :58080）")
            else:
                print("警告：frontend/ 目录不存在，请先创建 Vue 项目")
            print(f"Flask API 服务器已启动: http://localhost:{port}")
        else:
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

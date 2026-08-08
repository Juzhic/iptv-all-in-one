# -*- coding: utf-8 -*-
"""web 包 — Flask 应用工厂、BasicAuth 中间件、前端构建逻辑。"""
import hmac
import importlib.util
import json
import logging
import os
import pkgutil
import secrets
import subprocess
import sys as _sys
from urllib.parse import urlsplit

# Python 3.14 移除了 pkgutil.get_loader，当前 Flask 仍会调用它。
if not hasattr(pkgutil, 'get_loader'):
    def _compat_get_loader(module_or_name):
        name = module_or_name if isinstance(module_or_name, str) else getattr(module_or_name, '__name__', None)
        if not name:
            return None
        spec = importlib.util.find_spec(name)
        return spec.loader if spec else None

    pkgutil.get_loader = _compat_get_loader

from flask import Flask, request, Response, jsonify
from werkzeug.exceptions import BadRequest

from web.state import BASIC_AUTH_EXEMPT_PATHS

# ─────────────── 路径常量 ───────────────

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST_DIR = os.path.join(BASE_DIR, 'dist')
FRONTEND_DIR = os.path.join(BASE_DIR, 'frontend')
MAX_REQUEST_BYTES = 2 * 1024 * 1024
MAX_CONFIG_IMPORT_BYTES = 1024 * 1024

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def _load_root_iptv_env():
    """Load only IPTV_* values from the project .env for source/dev runs.

    Database variables are intentionally left to database/db_config.json when
    running from source.  Loading DB_HOST=mysql on a developer workstation
    would silently redirect the process to a Docker-only hostname.  Docker
    injects all required variables directly through Compose.
    """
    env_path = os.path.join(BASE_DIR, '.env')
    try:
        with open(env_path, 'r', encoding='utf-8-sig') as env_file:
            lines = env_file.readlines()
    except OSError:
        return

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        if not key.startswith('IPTV_'):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_root_iptv_env()


def _npm_cmd(args):
    """Build npm command list, cross-platform."""
    if _sys.platform == 'win32':
        return ['cmd', '/c', f'npm {args}']
    return ['npm'] + args.split()


# ─────────────── 前端构建辅助函数 ───────────────

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
            logger.warning('[前端] dist/ 不存在，且无前端源码 (frontend/package.json)，跳过构建')
            return
        logger.info('[前端] dist/ 不存在，正在自动构建...')
        _run_frontend_build()
        return

    if _frontend_deps_need_install():
        logger.info('[前端] 检测到依赖清单变更，正在重新安装依赖并构建...')
        _run_frontend_build()
        return

    # dist 存在，检查源码是否有更新
    try:
        dist_mtime = os.path.getmtime(index_html)
        for path in _iter_frontend_watch_files():
            if _safe_mtime(path) > dist_mtime:
                logger.info(f'[前端] 检测到前端文件更新 ({os.path.basename(path)})，正在重新构建...')
                _run_frontend_build()
                return
    except OSError:
        pass

    logger.info('[前端] 前端已是最新，无需构建 (dist/index.html 存在且源码未变更)')


def _run_frontend_build():
    """在 frontend/ 目录执行 npm run build。"""
    pkg = os.path.join(FRONTEND_DIR, 'package.json')
    if not os.path.exists(pkg):
        return

    if _frontend_deps_need_install():
        logger.info('[前端] 正在安装依赖 (npm install)...')
        install_result = subprocess.run(
            _npm_cmd('install --production=false'),
            cwd=FRONTEND_DIR,
            shell=False,
            capture_output=True,
            check=False,
            timeout=120,
        )
        if install_result.returncode != 0:
            stderr = install_result.stderr.decode('utf-8', errors='replace')[-500:] if install_result.stderr else ''
            logger.error(f'[前端] 依赖安装失败: {stderr}')
            return

    logger.info('[前端] 正在构建 (npm run build)...')
    result = subprocess.run(
        _npm_cmd('run build'),
        cwd=FRONTEND_DIR,
        shell=False,
        capture_output=True,
        timeout=180,
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
                    logger.info(f'[前端]   {clean}')
                except UnicodeEncodeError:
                    logger.info(f'[前端]   {clean.encode("utf-8", errors="replace").decode("ascii", errors="replace")}')
    if result.returncode == 0:
        logger.info('[前端] 构建完成')
    else:
        stderr = result.stderr.decode('utf-8', errors='replace')[-500:] if result.stderr else ''
        logger.error(f'[前端] 构建失败: {stderr}')


def _prepare_frontend_on_startup():
    """启动 Web 服务前预构建前端，避免首个请求时才发现 dist 缺失。"""
    _ensure_frontend()
    index_html = os.path.join(DIST_DIR, 'index.html')
    if not os.path.exists(index_html):
        raise RuntimeError('前端构建失败或 dist/index.html 不存在，请检查 frontend 构建日志')


# ─────────────── BasicAuth ───────────────

BASIC_AUTH_CONFIG_FILE = os.path.join(BASE_DIR, 'basic_auth.json')
BASIC_AUTH_DEFAULT_CONFIG = {
    'username': 'admin',
    'password': '',
    'realm': 'iptv-all-in-one',
}


def _env_flag(name):
    return os.environ.get(name, '').strip().lower() in {'1', 'true', 'yes', 'on'}


def _load_basic_auth_config():
    config = dict(BASIC_AUTH_DEFAULT_CONFIG)
    loaded = None
    try:
        with open(BASIC_AUTH_CONFIG_FILE, 'r', encoding='utf-8') as f:
            loaded = json.load(f)
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as exc:
        logger.warning('basic_auth.json 无法读取，将忽略该文件: %s', exc)

    if isinstance(loaded, dict):
        file_username = loaded.get('username')
        file_password = loaded.get('password')
        # A credential pair is accepted together.  A partial file must never
        # inherit the historical admin/admin fallback.
        if (
            isinstance(file_username, str) and file_username
            and isinstance(file_password, str) and file_password
        ):
            config['username'] = file_username
            config['password'] = file_password
        elif file_username is not None or file_password is not None:
            logger.warning('basic_auth.json 缺少完整的 username/password，已忽略其中的凭据')
        file_realm = loaded.get('realm')
        if isinstance(file_realm, str) and file_realm:
            config['realm'] = file_realm

    # 环境变量覆盖（优先级最高）
    env_username = os.environ.get('IPTV_AUTH_USERNAME')
    env_password = os.environ.get('IPTV_AUTH_PASSWORD')
    env_realm = os.environ.get('IPTV_AUTH_REALM')
    if env_username:
        config['username'] = env_username
    if env_password:
        config['password'] = env_password
    if env_realm:
        config['realm'] = env_realm

    if not config['password']:
        if _env_flag('IPTV_REQUIRE_STRONG_CREDENTIALS'):
            raise RuntimeError('IPTV_AUTH_PASSWORD 未设置，拒绝以严格模式启动')
        config['password'] = secrets.token_urlsafe(32)
        logger.warning(
            '未配置 Web 认证密码；本次进程使用临时随机密码。'
            '请运行 python generate_env.py 生成持久凭据。'
        )

    # 检测默认弱密码并警告
    if config['username'] == 'admin' and config['password'] == 'admin':
        logger.warning("安全警告: 检测到使用默认密码 (admin/admin)，建议立即修改 basic_auth.json 或设置环境变量 IPTV_AUTH_USERNAME/IPTV_AUTH_PASSWORD")

    return config


BASIC_AUTH_CONFIG = _load_basic_auth_config()
BASIC_AUTH_USER = BASIC_AUTH_CONFIG['username']
BASIC_AUTH_PASSWORD = BASIC_AUTH_CONFIG['password']
BASIC_AUTH_REALM = BASIC_AUTH_CONFIG['realm']

_KNOWN_WEAK_SECRETS = {
    'admin', 'changeme', 'default', 'letmein', 'mysql', 'password',
    'root', 'secret', 'test', '123456', '12345678', 'admin123',
}


def _is_weak_secret(value, minimum_length):
    if not isinstance(value, str) or len(value) < minimum_length:
        return True
    if value != value.strip() or value.casefold() in _KNOWN_WEAK_SECRETS:
        return True
    return len(set(value)) < 4


def _validate_runtime_credentials():
    """Fail closed in container deployments that opt into strict mode."""
    if not _env_flag('IPTV_REQUIRE_STRONG_CREDENTIALS'):
        return

    problems = []
    db_user = os.environ.get('DB_USER', '')
    db_password = os.environ.get('DB_PASSWORD', '')
    secret_key = os.environ.get('IPTV_SECRET_KEY', '')
    if not db_user or db_user.casefold() == 'root':
        problems.append('DB_USER 必须是专用的非 root 用户')
    if _is_weak_secret(db_password, 16):
        problems.append('DB_PASSWORD 必须是至少 16 位的强密码')
    if _is_weak_secret(BASIC_AUTH_PASSWORD, 16):
        problems.append('IPTV_AUTH_PASSWORD 必须是至少 16 位的强密码')
    if _is_weak_secret(secret_key, 32):
        problems.append('IPTV_SECRET_KEY 必须是至少 32 位的强随机值')

    if _env_flag('IPTV_REQUIRE_MYSQL_ROOT_PASSWORD'):
        root_password = os.environ.get('MYSQL_ROOT_PASSWORD', '')
        if _is_weak_secret(root_password, 16):
            problems.append('MYSQL_ROOT_PASSWORD 必须是至少 16 位的强密码')
        elif db_password and hmac.compare_digest(root_password, db_password):
            problems.append('MYSQL_ROOT_PASSWORD 与 DB_PASSWORD 必须不同')

    if problems:
        raise RuntimeError('凭据安全检查失败: ' + '; '.join(problems))


def _origin_key(value):
    """Normalize a serialized HTTP Origin for exact comparisons."""
    if not isinstance(value, str) or not value or value == 'null':
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    scheme = parsed.scheme.lower()
    if (
        scheme not in {'http', 'https'}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {'', '/'}
    ):
        return None
    if port is None:
        port = 443 if scheme == 'https' else 80
    return scheme, parsed.hostname.rstrip('.').lower(), port


def _trusted_origin_keys():
    trusted = set()
    for value in os.environ.get('IPTV_TRUSTED_ORIGINS', '').split(','):
        value = value.strip()
        if not value:
            continue
        normalized = _origin_key(value)
        if normalized is None:
            raise RuntimeError(f'IPTV_TRUSTED_ORIGINS 包含无效 Origin: {value!r}')
        trusted.add(normalized)
    return trusted


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


def require_basic_auth():
    """保护后台页面和 API；TXT/M3U 下载接口保持免登录，便于订阅客户端拉取。"""
    # Security trade-off: subscription URLs remain intentionally anonymous for
    # IPTV clients that cannot send BasicAuth.  Anyone who can reach the Web
    # port should be treated as able to read those generated playlists.
    if request.path in BASIC_AUTH_EXEMPT_PATHS:
        return None
    if _basic_auth_valid(request.authorization):
        return None
    return _basic_auth_challenge()


# ─────────────── 工具函数 ───────────────

def _finite_number_or_none(value):
    """把外部 API 的数字字段规整成 JSON number；无效值返回 None。"""
    from engine.utils import safe_number
    num = safe_number(value)
    if num is None:
        return None
    return int(num) if num.is_integer() else num


# ─────────────── 应用工厂 ───────────────

def create_app():
    """创建并配置 Flask 应用实例。"""
    _validate_runtime_credentials()
    trusted_origins = _trusted_origin_keys()
    secret_key = os.environ.get('IPTV_SECRET_KEY', '')
    if not secret_key:
        secret_key = secrets.token_urlsafe(48)
        logger.warning(
            '未配置 IPTV_SECRET_KEY；本次进程使用临时密钥。'
            '请运行 python generate_env.py 生成持久密钥。'
        )

    app = Flask(__name__, root_path=BASE_DIR, instance_path=BASE_DIR)
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
    app.config['MAX_CONTENT_LENGTH'] = MAX_REQUEST_BYTES
    app.config['MAX_FORM_MEMORY_SIZE'] = MAX_CONFIG_IMPORT_BYTES
    app.secret_key = secret_key

    @app.before_request
    def _before_request_basic_auth():
        return require_basic_auth()

    @app.before_request
    def _before_request_mutation_guard():
        if not request.path.startswith('/api/') or request.method not in {
            'POST', 'PUT', 'PATCH', 'DELETE'
        }:
            return None

        if request.headers.get('X-IPTV-Request') != '1':
            return jsonify({
                'ok': False,
                'error': '缺少有效的 X-IPTV-Request 请求标记',
            }), 403

        request_origin = _origin_key(request.headers.get('Origin'))
        expected_origin = _origin_key(request.host_url)
        if (
            request_origin is None
            or (request_origin != expected_origin and request_origin not in trusted_origins)
        ):
            return jsonify({'ok': False, 'error': 'Origin 不受信任'}), 403

        if (
            request.path == '/api/config/import'
            and request.content_length is not None
            and request.content_length > MAX_CONFIG_IMPORT_BYTES
        ):
            return jsonify({'ok': False, 'error': '配置导入最大支持 1 MiB'}), 413

        if request.path == '/api/config/import' and request.mimetype == 'multipart/form-data':
            return None
        if not request.is_json:
            return jsonify({'ok': False, 'error': '变更请求必须使用 JSON'}), 415
        try:
            request.get_json(cache=True, silent=False)
        except BadRequest:
            return jsonify({'ok': False, 'error': '请求正文不是有效 JSON'}), 400
        return None

    @app.after_request
    def add_no_cache_headers(response):
        """禁止浏览器和反向代理缓存动态页面/API，避免部署后看到旧页面。"""
        anonymous_feed_paths = BASIC_AUTH_EXEMPT_PATHS - {'/api/health'}
        dynamic_response = (
            'text/html' in response.content_type
            or response.content_type.startswith('application/json')
            or request.path.startswith('/api/')
        )
        # Anonymous playlist routes set short public caching and ETag headers in
        # their views. Preserve those headers; every other API remains no-store.
        if dynamic_response and request.path not in anonymous_feed_paths:
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0, private'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
            response.headers['Surrogate-Control'] = 'no-store'
            response.headers['X-Accel-Expires'] = '0'
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
        response.headers.setdefault('X-XSS-Protection', '1; mode=block')
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        response.headers.setdefault('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'")
        return response

    @app.teardown_appcontext
    def close_request_database_connection(_original_error):
        # The database helper is idempotent, rolls back unfinished explicit
        # transactions, and swallows cleanup errors so the request's original
        # exception remains the one Flask reports.
        from database import close_thread_connection
        close_thread_connection()

    @app.errorhandler(404)
    @app.errorhandler(405)
    def handle_client_error(e):
        return jsonify({'ok': False, 'error': str(e)}), e.code

    @app.errorhandler(413)
    def handle_request_too_large(_e):
        return jsonify({
            'ok': False,
            'error': f'请求正文不能超过 {MAX_REQUEST_BYTES // 1024 // 1024} MiB',
        }), 413

    @app.errorhandler(500)
    def handle_server_error(e):
        return jsonify({'ok': False, 'error': '服务器内部错误'}), 500

    return app

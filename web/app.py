# -*- coding: utf-8 -*-
"""web 包 — Flask 应用工厂、BasicAuth 中间件、前端构建逻辑。"""
import hmac
import importlib.util
import json
import logging
import os
import pkgutil
import subprocess
import sys

# Python 3.14 移除了 pkgutil.get_loader，当前 Flask 仍会调用它。
if not hasattr(pkgutil, 'get_loader'):
    def _compat_get_loader(module_or_name):
        name = module_or_name if isinstance(module_or_name, str) else getattr(module_or_name, '__name__', None)
        if not name:
            return None
        spec = importlib.util.find_spec(name)
        return spec.loader if spec else None

    pkgutil.get_loader = _compat_get_loader

from flask import Flask, request, Response

from web.state import BASIC_AUTH_EXEMPT_PATHS

# ─────────────── 路径常量 ───────────────

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST_DIR = os.path.join(BASE_DIR, 'dist')
FRONTEND_DIR = os.path.join(BASE_DIR, 'frontend')

logger = logging.getLogger(__name__)


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
            print('[前端] dist/ 不存在，且无前端源码 (frontend/package.json)，跳过构建')
            return
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

    print('[前端] 前端已是最新，无需构建 (dist/index.html 存在且源码未变更)')


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


# ─────────────── BasicAuth ───────────────

BASIC_AUTH_CONFIG_FILE = os.path.join(BASE_DIR, 'basic_auth.json')
BASIC_AUTH_DEFAULT_CONFIG = {
    'username': 'admin',
    'password': 'admin',
    'realm': 'IPTV Test',
}


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


def require_basic_auth():
    """保护后台页面和 API；TXT/M3U 下载接口保持免登录，便于订阅客户端拉取。"""
    if request.path in BASIC_AUTH_EXEMPT_PATHS:
        return None
    if _basic_auth_valid(request.authorization):
        return None
    return _basic_auth_challenge()


# ─────────────── 工具函数 ───────────────

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


# ─────────────── 应用工厂 ───────────────

def create_app():
    """创建并配置 Flask 应用实例。"""
    app = Flask(__name__, root_path=BASE_DIR, instance_path=BASE_DIR)
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

    @app.before_request
    def _before_request_basic_auth():
        return require_basic_auth()

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

    return app

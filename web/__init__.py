# -*- coding: utf-8 -*-
"""
web 包 — iptv-all-in-one 管理后台。

gunicorn 入口: gunicorn web:app
"""
import logging
import os

import pymysql

from web.app import create_app, _ensure_frontend
import database as db

# 启动时即导入扫描模块，避免请求内并发 import 导致死锁（Python 3.14+）
try:
    import scanner_integration as _scanner_module
except ImportError:
    _scanner_module = None

import web.state as _state
_state._scanner_module = _scanner_module

# 创建 Flask 应用
app = create_app()

# 模块级初始化（兼容 uWSGI / gunicorn 等 WSGI 服务器）
# 数据库暂未就绪仍沿用延迟重试策略；一旦数据库已连接，API Key
# 解密/明文迁移失败属于安全错误，必须拒绝启动而不能降级继续。
_db_ready = False


def _strict_credentials_enabled():
    return os.environ.get('IPTV_REQUIRE_STRONG_CREDENTIALS', '').strip().lower() in {
        '1', 'true', 'yes', 'on'
    }


def _is_transient_connection_error(error):
    """Recognize only connectivity failures that may recover without changes."""
    current = error
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, pymysql.err.OperationalError):
            code = current.args[0] if current.args else None
            if code in {1040, 1129, 1130, 1203, 2002, 2003, 2006, 2013}:
                return True
            return False
        if isinstance(current, (ConnectionError, TimeoutError)):
            return True
        if isinstance(current, OSError) and getattr(current, 'winerror', None) in {
            10054, 10060, 10061, 11001
        }:
            return True
        current = current.__cause__ or current.__context__
    return False


try:
    db.init_db()
except Exception as error:
    if _strict_credentials_enabled() or not _is_transient_connection_error(error):
        logging.getLogger(__name__).exception('数据库初始化失败，拒绝启动')
        raise
    logging.getLogger(__name__).warning(
        '数据库连接暂不可用，将在后续请求中重试: %s', error
    )
else:
    _db_ready = True
    try:
        db.migrate_from_json()
    except Exception:
        # Authentication, DDL/schema and data migration failures cannot be
        # treated as ordinary readiness lag.
        logging.getLogger(__name__).exception('数据库数据迁移失败，拒绝启动')
        raise

if _db_ready:
    try:
        from scanner_integration.config_bridge import get_scan_config
        get_scan_config()
    except Exception:
        logging.getLogger(__name__).exception(
            "扫描 API Key 解密或安全迁移失败，拒绝启动"
        )
        raise
try:
    db.clear_run_progress()
except Exception:
    pass

if _scanner_module is not None:
    try:
        _scanner_module.init_bridge()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"扫描后台任务启动失败: {e}")

# 检查前端是否需要构建
_ensure_frontend()

# 注册所有路由蓝图（延迟导入，避免在 aiohttp 缺失时阻塞整个包）
try:
    from web.routes import register_all_blueprints
    register_all_blueprints(app)
except ImportError as e:
    import logging
    logging.getLogger(__name__).warning(f"部分路由注册失败（可能缺少依赖）: {e}")

# 按配置启动调度器
try:
    from web.scheduler import _start_scheduler_from_config
    _start_scheduler_from_config()
except Exception as e:
    import logging
    logging.getLogger(__name__).warning(f"调度器启动失败: {e}")

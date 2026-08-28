# -*- coding: utf-8 -*-
"""
web 包 — iptv-all-in-one 管理后台。

gunicorn 入口: gunicorn web:app
"""
import logging
import os

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

# 模块级初始化（兼容 uWSGI / gunicorn 等 WSGI 服务器）。生产 Compose
# 显式要求数据库可用；源码工具和不涉及数据库的单元测试仍可导入模块。
_database_required = os.environ.get('IPTV_REQUIRE_DATABASE', '').strip().lower() \
    in {'1', 'true', 'yes', 'on'}
_db_ready = False
try:
    db.init_db()
except Exception as error:
    logging.getLogger(__name__).exception('PostgreSQL 初始化失败: %s', error)
    if _database_required:
        raise
else:
    _db_ready = True

if _db_ready:
    try:
        db.migrate_from_json()
        from scanner_integration.config_bridge import get_scan_config
        get_scan_config()
    except Exception as error:
        logging.getLogger(__name__).exception('数据库内容迁移或读取失败: %s', error)
        if _database_required:
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

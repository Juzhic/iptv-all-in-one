# -*- coding: utf-8 -*-
"""
web 包 — IPTV 测速管理后台。

gunicorn 入口: gunicorn web:app
"""
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
db.init_db()
db.migrate_from_json()
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

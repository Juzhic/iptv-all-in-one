# -*- coding: utf-8 -*-
"""
web 包 — iptv-all-in-one 管理后台。

gunicorn 入口: gunicorn web:app
"""
import logging

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
# The long-running Web process must remain available while an old deployment
# is being repaired.  Database helpers and the explicit migrate-2-0 command
# still fail on real schema/key migration errors, but importing the WSGI app
# reports those errors instead of turning an image pull into a restart loop.
_db_ready = False

try:
    db.init_db()
except Exception as error:
    logging.getLogger(__name__).exception(
        '数据库初始化未完成，兼容模式继续启动；数据库恢复后请求会重试。'
        '如为结构迁移或权限错误，请在备份后运行一次性迁移并检查日志: %s',
        error,
    )
else:
    _db_ready = True
    try:
        db.migrate_from_json()
    except Exception as error:
        logging.getLogger(__name__).exception(
            '旧 JSON 数据迁移未完成，兼容模式继续启动: %s', error
        )

if _db_ready:
    try:
        from scanner_integration.config_bridge import get_scan_config
        get_scan_config()
    except Exception as error:
        logging.getLogger(__name__).exception(
            '扫描 API Key 读取或迁移未完成，兼容模式继续启动；'
            '受影响的扫描 Key 在修复前不可用: %s',
            error,
        )
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

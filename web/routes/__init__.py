# -*- coding: utf-8 -*-
"""web.routes 包 — 蓝图注册入口。"""


def register_all_blueprints(app):
    from .spa import spa_bp
    from .config import config_bp
    from .history import history_bp
    from .test_control import test_control_bp
    from .download import download_bp
    from .scan import scan_bp
    from .subscribe import subscribe_bp
    from .health import health_bp
    from .ip_scan import ip_scan_bp

    app.register_blueprint(spa_bp)
    app.register_blueprint(config_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(test_control_bp)
    app.register_blueprint(download_bp)
    app.register_blueprint(scan_bp)
    app.register_blueprint(subscribe_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(ip_scan_bp)

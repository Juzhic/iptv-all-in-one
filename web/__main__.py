# -*- coding: utf-8 -*-
"""python -m web — 直接启动 Web 服务。"""
import sys
import os
import subprocess

from web import app
from web.app import BASE_DIR, _prepare_frontend_on_startup
from engine import load_config, DEFAULT_CONFIG

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
        from web.scheduler import _ensure_scheduler_started
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
                if sys.platform == 'win32':
                    subprocess.Popen(
                        ['cmd', '/c', 'npm run dev'],
                        cwd=frontend_dir,
                        creationflags=subprocess.CREATE_NEW_CONSOLE,
                    )
                else:
                    subprocess.Popen(
                        ['npm', 'run', 'dev'],
                        cwd=frontend_dir,
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

# -*- coding: utf-8 -*-
"""web 包 — 共享可变状态。

所有模块从这里读写状态，避免循环导入。
"""
import collections
import os
import threading

# ─── 允许通过 Web 编辑的数据 key ───
ALLOWED_DATA_KEYS = {'alias', 'demo', 'subscribe'}

# ─── BasicAuth 免认证路径 ───
BASIC_AUTH_EXEMPT_PATHS = {'/api/download/txt', '/api/download/m3u'}

# ─── 测试运行状态 ───
_test_running = False
_test_lock = threading.Lock()
_test_stop_event = threading.Event()
_test_active_token = None

# 测试进度追踪
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
_test_log_lines = collections.deque(maxlen=200)
_test_log_seq = 0

# ─── 调度器状态 ───
_next_scheduled_run = None
_scheduler_running = False
_scheduler_thread = None
_scheduler_thread_lock = threading.Lock()
_scheduler_lock_handle = None
_scheduler_owner = f'pid:{os.getpid()}'

# ─── 扫描模块引用（__init__.py 启动时填充） ───
_scanner_module = None


# ─── setter 函数（处理需要 global 声明的重新赋值） ───

def set_test_running(value):
    global _test_running
    _test_running = value


def set_test_stop_event(event):
    global _test_stop_event
    _test_stop_event = event


def set_test_active_token(token):
    global _test_active_token
    _test_active_token = token


def inc_test_log_seq():
    global _test_log_seq
    _test_log_seq += 1
    return _test_log_seq


def reset_test_log_seq():
    global _test_log_seq
    _test_log_seq = 0


def set_scheduler_running(value):
    global _scheduler_running
    _scheduler_running = value


def set_scheduler_thread(thread):
    global _scheduler_thread
    _scheduler_thread = thread


def set_next_scheduled_run(value):
    global _next_scheduled_run
    _next_scheduled_run = value


def set_scheduler_lock_handle(handle):
    global _scheduler_lock_handle
    _scheduler_lock_handle = handle

# -*- coding: utf-8 -*-
"""web.routes.config — 配置管理与数据文件 API。

路由:
    GET  /api/config        — api_get_config() 读取当前配置
    POST /api/config        — api_save_config() 保存配置
    GET  /api/text/<key>    — api_get_text() 读取数据文件内容
    POST /api/text/<key>    — api_save_text() 保存数据文件内容
    POST /api/reset-demo    — api_reset_demo() 恢复 demo 模板
"""
from flask import Blueprint, request, jsonify

from engine import load_config, DEFAULT_CONFIG
from database import (
    get_config_data,
    set_config_data,
    DEFAULT_DEMO,
    get_config,
    save_config as db_save_config,
    clear_scheduler_state,
)
from web.state import ALLOWED_DATA_KEYS
from web.scheduler import _ensure_scheduler_started

config_bp = Blueprint('config', __name__)


# ─────────────── 配置 API ───────────────

@config_bp.route('/api/config', methods=['GET'])
def api_get_config():
    """读取当前配置（从数据库，合并默认值）。"""
    cfg = load_config()
    return jsonify(cfg)


@config_bp.route('/api/config', methods=['POST'])
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

@config_bp.route('/api/text/<key>', methods=['GET'])
def api_get_text(key):
    """读取配置数据内容。"""
    if key not in ALLOWED_DATA_KEYS:
        return jsonify({'error': '不允许访问该数据'}), 403
    content = get_config_data(key)
    return jsonify({'content': content, 'filename': key})


@config_bp.route('/api/text/<key>', methods=['POST'])
def api_save_text(key):
    """保存配置数据内容。"""
    if key not in ALLOWED_DATA_KEYS:
        return jsonify({'error': '不允许访问该数据'}), 403
    data = request.get_json(silent=True)
    if not data or 'content' not in data:
        return jsonify({'error': '缺少 content 字段'}), 400
    set_config_data(key, data['content'])
    return jsonify({'ok': True, 'filename': key})


@config_bp.route('/api/reset-demo', methods=['POST'])
def api_reset_demo():
    """恢复 demo 模板为默认内容。"""
    set_config_data('demo', DEFAULT_DEMO)
    return jsonify({'ok': True, 'message': '已恢复默认模板'})

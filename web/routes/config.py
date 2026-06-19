# -*- coding: utf-8 -*-
"""web.routes.config — 配置管理与数据文件 API。

路由:
    GET  /api/config        — api_get_config() 读取当前配置
    POST /api/config        — api_save_config() 保存配置
    GET  /api/text/<key>    — api_get_text() 读取数据文件内容
    POST /api/text/<key>    — api_save_text() 保存数据文件内容
    POST /api/reset-demo    — api_reset_demo() 恢复 demo 模板
"""
import re

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
from web.state import is_allowed_data_key
from web.scheduler import _ensure_scheduler_started

config_bp = Blueprint('config', __name__)

_RESERVED_PROFILE_NAMES = {'config', 'scan_config', 'subscribe', 'demo', 'alias', 'profiles', 'profile'}


def _sanitize_profile_name(name):
    """Validate profile name: alphanumeric, Chinese, hyphens, underscores only."""
    name = name.strip()
    if not name or len(name) > 50:
        return None
    if not re.match(r'^[\w\u4e00-\u9fff-]+$', name):
        return None
    if name.lower() in _RESERVED_PROFILE_NAMES:
        return None
    return name


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
    numeric_keys = {'test_duration', 'max_workers', 'max_ffmpeg_workers', 'max_urls_per_channel',
                    'min_width', 'min_height', 'run_interval_minutes', 'system_bandwidth_limit_MBps',
                    'system_memory_limit_percent', 'webhook_min_pass_rate', 'ffmpeg_timeout',
                    'min_bandwidth_MBps', 'bandwidth_compensation_MBps', 'h265_bandwidth_ratio'}
    for key, value in data.items():
        if key in valid_keys:
            if key in numeric_keys:
                try:
                    cfg[key] = int(value) if key not in ('system_bandwidth_limit_MBps', 'system_memory_limit_percent') else float(value)
                except (TypeError, ValueError):
                    pass
            else:
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
    if not is_allowed_data_key(key):
        return jsonify({'error': '不允许访问该数据'}), 403
    content = get_config_data(key)
    return jsonify({'content': content, 'filename': key})


@config_bp.route('/api/text/<key>', methods=['POST'])
def api_save_text(key):
    """保存配置数据内容。"""
    if not is_allowed_data_key(key):
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


# ─────────────── 配置导入导出 API ───────────────

@config_bp.route('/api/config/export')
def api_config_export():
    """Export all configuration as a JSON file for backup."""
    import json
    from io import BytesIO
    from flask import send_file

    keys = ['config', 'subscribe', 'demo', 'alias', 'scan_config']
    export_data = {}
    for key in keys:
        try:
            content = get_config_data(key)
            if content:
                export_data[key] = content
        except Exception:
            pass

    buf = BytesIO()
    buf.write(json.dumps(export_data, ensure_ascii=False, indent=2).encode('utf-8'))
    buf.seek(0)
    return send_file(buf, mimetype='application/json',
                     as_attachment=True, download_name='iptv-config-backup.json')


@config_bp.route('/api/config/import', methods=['POST'])
def api_config_import():
    """Import configuration from a JSON file."""
    import json

    if not request.files:
        return jsonify({'error': '请上传配置文件'}), 400

    file = request.files.get('file')
    if not file:
        return jsonify({'error': '请上传配置文件'}), 400

    try:
        content = file.read().decode('utf-8')
        data = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        return jsonify({'error': f'文件格式错误: {e}'}), 400

    if not isinstance(data, dict):
        return jsonify({'error': '配置文件格式错误，应为 JSON 对象'}), 400

    valid_keys = {'config', 'subscribe', 'demo', 'alias', 'scan_config'}
    imported = []
    for key, value in data.items():
        if key in valid_keys:
            try:
                set_config_data(key, value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
                imported.append(key)
            except Exception:
                pass

    try:
        clear_scheduler_state()
    except Exception:
        pass

    return jsonify({'ok': True, 'imported': imported})


# ─────────────── 频道发现 API ───────────────

@config_bp.route('/api/discover', methods=['GET'])
def api_discover():
    """Scan subscription sources and discover available channels."""
    from engine.discovery import discover_channels
    try:
        result = discover_channels()
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': f'扫描失败: {e}'}), 500


@config_bp.route('/api/discover/merge', methods=['POST'])
def api_discover_merge():
    """Merge selected channels into the demo template."""
    from engine.discovery import merge_channels_into_demo
    data = request.get_json(silent=True)
    if not data or 'channels' not in data:
        return jsonify({'error': '缺少 channels 字段'}), 400

    channels = data['channels']
    if not isinstance(channels, list):
        return jsonify({'error': 'channels 应为列表'}), 400

    try:
        result = merge_channels_into_demo(channels)
        return jsonify({'ok': True, **result})
    except Exception as e:
        return jsonify({'error': f'合并失败: {e}'}), 500


# ─────────────── 多方案管理 API ───────────────

@config_bp.route('/api/profiles')
def api_list_profiles():
    """List all profile configurations."""
    import json
    raw = get_config_data('profiles')
    if raw:
        try:
            return jsonify(json.loads(raw))
        except json.JSONDecodeError:
            pass
    return jsonify([{'name': '默认', 'key': 'demo', 'description': '默认频道方案'}])


@config_bp.route('/api/profiles', methods=['POST'])
def api_create_profile():
    """Create a new profile."""
    import json
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': '请求数据无效'}), 400
    name = _sanitize_profile_name(data.get('name', ''))
    if not name:
        return jsonify({'error': '方案名称无效（只允许中文、字母、数字、下划线、连字符，最长50字符）'}), 400
    description = data.get('description', '').strip()
    key = f'profile:{name}'
    raw = get_config_data('profiles')
    profiles = json.loads(raw) if raw else [{'name': '默认', 'key': 'demo', 'description': '默认频道方案'}]
    if any(p['key'] == key for p in profiles):
        return jsonify({'error': '方案已存在'}), 400
    profiles.append({'name': name, 'key': key, 'description': description})
    set_config_data('profiles', json.dumps(profiles, ensure_ascii=False))
    if data.get('source') == 'copy':
        demo = get_config_data('demo')
        set_config_data(key, demo or '')
    else:
        set_config_data(key, f'{name},#genre#\n')
    return jsonify({'ok': True, 'key': key})


@config_bp.route('/api/profiles/<name>', methods=['DELETE'])
def api_delete_profile(name):
    """Delete a profile."""
    import json
    name = _sanitize_profile_name(name)
    if not name:
        return jsonify({'error': '方案名称无效'}), 400
    key = f'profile:{name}'
    if key == 'demo':
        return jsonify({'error': '不能删除默认方案'}), 400
    raw = get_config_data('profiles')
    profiles = json.loads(raw) if raw else []
    profiles = [p for p in profiles if p['key'] != key]
    set_config_data('profiles', json.dumps(profiles, ensure_ascii=False))
    set_config_data(key, '')
    return jsonify({'ok': True})

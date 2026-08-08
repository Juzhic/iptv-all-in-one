# -*- coding: utf-8 -*-
"""web.routes.config — 配置管理与数据文件 API。

路由:
    GET  /api/config        — api_get_config() 读取当前配置
    POST /api/config        — api_save_config() 保存配置
    GET  /api/text/<key>    — api_get_text() 读取数据文件内容
    POST /api/text/<key>    — api_save_text() 保存数据文件内容
    POST /api/reset-demo    — api_reset_demo() 恢复 demo 模板
"""
import json
import ipaddress
import math
import os
import re
from urllib.parse import urlsplit

from flask import Blueprint, request, jsonify

from engine import load_config, DEFAULT_CONFIG
from engine.test_engine import CONFIG_SCHEMA_VERSION
from database import (
    get_config_data,
    set_config_data,
    DEFAULT_DEMO,
    get_config,
    save_config as db_save_config,
    clear_scheduler_state,
)
import database.db as _database_db
from web.state import is_allowed_data_key
from web.scheduler import _ensure_scheduler_started, _reload_scheduler_config

config_bp = Blueprint('config', __name__)

_RESERVED_PROFILE_NAMES = {'config', 'scan_config', 'subscribe', 'demo', 'alias', 'profiles', 'profile'}
MAX_IMPORT_BYTES = 1024 * 1024
MAX_CONFIG_URL_LENGTH = 2048

_INT_RANGES = {
    'test_duration': (1, 3600),
    'max_workers': (1, 100),
    'max_ffmpeg_workers': (1, 64),
    'max_urls_per_channel': (0, 1000),
    'min_width': (0, 7680),
    'min_height': (0, 4320),
    'run_interval_minutes': (1, 10080),
}
_FLOAT_RANGES = {
    'system_bandwidth_limit_MBps': (0, 100000),
    'system_memory_limit_percent': (0, 100),
    'min_bandwidth_MBps': (0, 100000),
    'bandwidth_compensation_MBps': (0, 100000),
    'h265_bandwidth_ratio': (0, 1),
}
_BOOL_KEYS = {'show_update_time', 'include_scan_results_in_test'}
_ENUM_VALUES = {
    'run_mode': {'once', 'times', 'interval'},
    'update_time_position': {'top', 'bottom'},
}
_CONTROL_CHARS = re.compile(r'[\x00-\x1f\x7f-\x9f]')


class ConfigValidationError(ValueError):
    """Raised when a configuration payload must not be persisted."""


def _validate_http_url(key, value, *, allow_empty=False):
    if not isinstance(value, str):
        raise ConfigValidationError(f'{key} 必须是字符串')
    if not value and allow_empty:
        return ''
    if not value:
        raise ConfigValidationError(f'{key} 不能为空')
    if value != value.strip():
        raise ConfigValidationError(f'{key} 不能包含首尾空白')
    if len(value) > MAX_CONFIG_URL_LENGTH:
        raise ConfigValidationError(f'{key} 最长为 {MAX_CONFIG_URL_LENGTH} 个字符')
    if _CONTROL_CHARS.search(value):
        raise ConfigValidationError(f'{key} 不能包含控制字符')
    try:
        parsed = urlsplit(value)
        # Accessing port also validates malformed values such as ":abc".
        parsed.port
    except ValueError as exc:
        raise ConfigValidationError(f'{key} 不是有效 URL') from exc
    if parsed.scheme.lower() not in {'http', 'https'} or not parsed.hostname:
        raise ConfigValidationError(f'{key} 仅支持包含主机名的 HTTP(S) URL')
    if key == 'logo_base_url':
        return value.rstrip('/')
    return value


def _normalize_run_times_strict(value):
    if isinstance(value, str):
        values = [item.strip() for item in re.split(r'[,;，]', value) if item.strip()]
    elif isinstance(value, list):
        values = value
    else:
        raise ConfigValidationError('run_times 必须是时间列表或逗号分隔字符串')

    normalized = []
    for item in values:
        if not isinstance(item, str):
            raise ConfigValidationError('run_times 中的每一项都必须是字符串')
        match = re.fullmatch(r'(\d{1,2}):(\d{1,2})', item.strip())
        if not match:
            raise ConfigValidationError(f'无效的执行时间: {item!r}')
        hour, minute = int(match.group(1)), int(match.group(2))
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ConfigValidationError(f'无效的执行时间: {item!r}')
        normalized.append(f'{hour:02d}:{minute:02d}')
    return sorted(set(normalized))


def _validate_config_value(key, value):
    if key == 'schema_version':
        if isinstance(value, bool) or value != CONFIG_SCHEMA_VERSION:
            raise ConfigValidationError(
                f'schema_version 必须为 {CONFIG_SCHEMA_VERSION}'
            )
        return CONFIG_SCHEMA_VERSION

    if key in _INT_RANGES:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigValidationError(f'{key} 必须是整数')
        lo, hi = _INT_RANGES[key]
        if not lo <= value <= hi:
            raise ConfigValidationError(f'{key} 必须在 {lo} 到 {hi} 之间')
        return value

    if key in _FLOAT_RANGES:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigValidationError(f'{key} 必须是数值')
        value = float(value)
        lo, hi = _FLOAT_RANGES[key]
        if not math.isfinite(value) or not lo <= value <= hi:
            raise ConfigValidationError(f'{key} 必须在 {lo} 到 {hi} 之间')
        return value

    if key in _BOOL_KEYS:
        if not isinstance(value, bool):
            raise ConfigValidationError(f'{key} 必须是布尔值')
        return value

    if key in _ENUM_VALUES:
        if value not in _ENUM_VALUES[key]:
            choices = ', '.join(sorted(_ENUM_VALUES[key]))
            raise ConfigValidationError(f'{key} 只能是: {choices}')
        return value

    if key == 'run_times':
        return _normalize_run_times_strict(value)
    if key == 'logo_base_url':
        return _validate_http_url(key, value)
    if key == 'epg_url':
        return _validate_http_url(key, value, allow_empty=True)

    raise ConfigValidationError(f'不支持的配置项: {key}')


def _normalize_config_payload(payload, *, base=None, allow_empty=False):
    if not isinstance(payload, dict):
        raise ConfigValidationError('配置必须是 JSON 对象')
    if not payload and not allow_empty:
        raise ConfigValidationError('配置不能为空')

    unknown = sorted(set(payload) - set(DEFAULT_CONFIG))
    if unknown:
        raise ConfigValidationError(f'包含未知配置项: {", ".join(unknown)}')

    normalized = {}
    errors = []
    for key, value in payload.items():
        try:
            normalized[key] = _validate_config_value(key, value)
        except ConfigValidationError as exc:
            errors.append(str(exc))
    if errors:
        raise ConfigValidationError('; '.join(errors))

    result = dict(base or {})
    result.update(normalized)
    result['schema_version'] = CONFIG_SCHEMA_VERSION
    return result


def _safe_current_config(source=None):
    """Return stored config filtered through the current schema and defaults."""
    source = source if isinstance(source, dict) else get_config(DEFAULT_CONFIG)
    cleaned = dict(DEFAULT_CONFIG)
    for key in DEFAULT_CONFIG:
        if key == 'schema_version' or key not in source:
            continue
        try:
            cleaned[key] = _validate_config_value(key, source[key])
        except ConfigValidationError:
            # Legacy or corrupt values are never reflected back into exports or
            # future writes; the safe current default wins instead.
            pass
    cleaned['schema_version'] = CONFIG_SCHEMA_VERSION
    return cleaned


def _validation_response(exc):
    return jsonify({'ok': False, 'error': str(exc)}), 422


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
    cfg = _safe_current_config(load_config())
    return jsonify({'ok': True, 'data': cfg})


@config_bp.route('/api/config/security-status', methods=['GET'])
def api_config_security_status():
    """Expose only non-secret deployment warnings needed by the settings UI."""
    hosts = []
    for item in os.environ.get('IPTV_INSECURE_TLS_HOSTS', '').split(','):
        host = item.strip().lower()
        if not host or len(host) > 253 or _CONTROL_CHARS.search(host):
            continue
        try:
            ipaddress.ip_address(host)
        except ValueError:
            try:
                ascii_host = host.encode('idna').decode('ascii')
            except UnicodeError:
                continue
            labels = ascii_host.rstrip('.').split('.')
            if not labels or any(
                not label
                or len(label) > 63
                or label.startswith('-')
                or label.endswith('-')
                or re.fullmatch(r'[a-z0-9-]+', label) is None
                for label in labels
            ):
                continue
        hosts.append(host)
    hosts = sorted(set(hosts))
    return jsonify({
        'ok': True,
        'data': {
            'insecure_tls_hosts_enabled': bool(hosts),
            'insecure_tls_hosts': hosts,
        },
    })


@config_bp.route('/api/config', methods=['POST'])
def api_save_config():
    """保存配置到数据库。"""
    data = request.get_json(silent=True)
    try:
        current = _safe_current_config(get_config(DEFAULT_CONFIG))
        cfg = _normalize_config_payload(data, base=current)
    except ConfigValidationError as exc:
        return _validation_response(exc)

    db_save_config(cfg)
    if cfg.get('run_mode', 'once') == 'once':
        _reload_scheduler_config()
        try:
            clear_scheduler_state()
        except Exception:
            pass
    else:
        _ensure_scheduler_started(cfg)
    updated_keys = [key for key in data if key != 'schema_version']
    return jsonify({'ok': True, 'data': {'updated': updated_keys, 'config': cfg}})


# ─────────────── 数据文件 API ───────────────

@config_bp.route('/api/text/<key>', methods=['GET'])
def api_get_text(key):
    """读取配置数据内容。"""
    if not is_allowed_data_key(key):
        return jsonify({'ok': False, 'error': '不允许访问该数据'}), 403
    content = get_config_data(key)
    return jsonify({'ok': True, 'data': {'content': content, 'filename': key}})


@config_bp.route('/api/text/<key>', methods=['POST'])
def api_save_text(key):
    """保存配置数据内容。"""
    if not is_allowed_data_key(key):
        return jsonify({'ok': False, 'error': '不允许访问该数据'}), 403
    data = request.get_json(silent=True)
    if not data or 'content' not in data:
        return jsonify({'ok': False, 'error': '缺少 content 字段'}), 400
    set_config_data(key, data['content'])
    return jsonify({'ok': True, 'data': {'filename': key}})


@config_bp.route('/api/reset-demo', methods=['POST'])
def api_reset_demo():
    """恢复 demo 模板为默认内容。"""
    set_config_data('demo', DEFAULT_DEMO)
    return jsonify({'ok': True, 'message': '已恢复默认模板'})


# ─────────────── 配置导入导出 API ───────────────

_IMPORT_DATA_KEYS = ('config', 'subscribe', 'demo', 'alias', 'scan_config')


def _prepare_import_entries(data):
    if not isinstance(data, dict):
        raise ConfigValidationError('配置文件必须是 JSON 对象')

    version = data.get('schema_version')
    if isinstance(version, bool) or version != CONFIG_SCHEMA_VERSION:
        raise ConfigValidationError(
            f'配置文件 schema_version 必须为 {CONFIG_SCHEMA_VERSION}'
        )

    allowed = {'schema_version', *_IMPORT_DATA_KEYS}
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ConfigValidationError(f'配置文件包含未知项目: {", ".join(unknown)}')

    entries = []
    for key in _IMPORT_DATA_KEYS:
        if key not in data:
            continue
        value = data[key]
        if key == 'config':
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError as exc:
                    raise ConfigValidationError('config 不是有效 JSON 对象') from exc
            normalized = _normalize_config_payload(
                value, base=DEFAULT_CONFIG, allow_empty=True
            )
            content = json.dumps(normalized, ensure_ascii=False, indent=2)
        elif key == 'scan_config':
            if isinstance(value, str):
                try:
                    parsed = json.loads(value)
                except json.JSONDecodeError as exc:
                    raise ConfigValidationError('scan_config 不是有效 JSON 对象') from exc
            else:
                parsed = value
            if not isinstance(parsed, dict):
                raise ConfigValidationError('scan_config 必须是 JSON 对象')
            content = _prepare_scan_config_for_storage(parsed)
        else:
            if not isinstance(value, str):
                raise ConfigValidationError(f'{key} 必须是字符串')
            if '\x00' in value:
                raise ConfigValidationError(f'{key} 不能包含 NUL 字符')
            content = value
        entries.append((key, content))

    if not entries:
        raise ConfigValidationError('配置文件没有可导入的项目')
    return entries


def _prepare_scan_config_for_storage(imported):
    """Normalize and encrypt imported scanner API keys before any DB write."""
    from scanner_integration.config_bridge import (
        DEFAULT_SCAN_CONFIG,
        _API_KEY_PLATFORMS,
        _decrypt_stored_keys,
        _encrypt_persisted_keys,
        _normalize_scan_config,
        get_scan_config,
    )
    from scanner_integration.secure_keys import SecretConfigurationError

    imported = dict(imported)
    imported.pop('api_key_metadata', None)
    legacy_aliases = {
        f'{platform}_key' for platform in _API_KEY_PLATFORMS
    }
    allowed = set(DEFAULT_SCAN_CONFIG) | legacy_aliases
    unknown = sorted(set(imported) - allowed)
    if unknown:
        raise ConfigValidationError(
            f'scan_config 包含未知配置项: {", ".join(unknown)}'
        )

    # Validate existing ciphertext and incoming ciphertext/plaintext before the
    # transaction. get_scan_config returns runtime plaintext and performs any
    # independent legacy migration required by the installed deployment.
    current = dict(get_scan_config())
    try:
        incoming, _ = _decrypt_stored_keys(imported)
    except (SecretConfigurationError, ValueError) as exc:
        raise ConfigValidationError('scan_config 中的 API Key 无法安全解密') from exc
    merged = dict(current)
    for platform in _API_KEY_PLATFORMS:
        key_fields = {
            f'{platform}_api_keys',
            f'{platform}_api_key',
            f'{platform}_key',
        }
        if key_fields & set(imported):
            # An explicit key field (including an empty list) replaces the
            # platform's prior credentials instead of being repopulated by a
            # compatibility alias from the current runtime config.
            merged[f'{platform}_api_keys'] = []
            merged[f'{platform}_api_key'] = ''
            merged[f'{platform}_key'] = ''
    merged.update(incoming)

    normalized = _normalize_scan_config(merged)
    try:
        persisted = _encrypt_persisted_keys(normalized)
    except (SecretConfigurationError, ValueError) as exc:
        raise ConfigValidationError('scan_config 中的 API Key 无法安全加密') from exc
    for alias in legacy_aliases:
        persisted.pop(alias, None)
    return json.dumps(persisted, ensure_ascii=False, indent=2)


def _export_scan_config_without_keys():
    """Return scanner settings plus key counts, never key material."""
    from scanner_integration.config_bridge import (
        _API_KEY_PLATFORMS,
        DEFAULT_SCAN_CONFIG,
        get_scan_config,
    )

    runtime = dict(get_scan_config())
    counts = {}
    for platform in _API_KEY_PLATFORMS:
        values = runtime.get(f'{platform}_api_keys', [])
        counts[platform] = len(values) if isinstance(values, list) else 0

    sensitive_names = set()
    for platform in _API_KEY_PLATFORMS:
        sensitive_names.update({
            f'{platform}_api_keys',
            f'{platform}_api_key',
            f'{platform}_key',
        })
    exported = {
        key: value for key, value in runtime.items()
        if key in DEFAULT_SCAN_CONFIG and key not in sensitive_names
    }
    exported['api_key_metadata'] = {'counts': counts}
    return exported


def _write_import_entries_atomically(entries):
    """Persist every validated config_data row in one DB transaction."""
    with _database_db._write_lock:
        conn = _database_db._get_conn()
        updated_at = _database_db.now_str()
        with conn.transaction():
            for key, content in entries:
                conn.execute(
                    "REPLACE INTO config_data (`key`, content, updated_at) VALUES (%s, %s, %s)",
                    (key, content, updated_at),
                )


def _import_too_large_response():
    return jsonify({'ok': False, 'error': '配置导入最大支持 1 MiB'}), 413

@config_bp.route('/api/config/export', methods=['GET'])
def api_config_export():
    """Export all configuration as a JSON file for backup."""
    from io import BytesIO
    from flask import send_file

    export_data = {
        'schema_version': CONFIG_SCHEMA_VERSION,
        'config': _safe_current_config(load_config()),
        'scan_config': _export_scan_config_without_keys(),
    }
    for key in ('subscribe', 'demo', 'alias'):
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
    if request.content_length is not None and request.content_length > MAX_IMPORT_BYTES:
        return _import_too_large_response()

    if request.is_json:
        if len(request.get_data(cache=True)) > MAX_IMPORT_BYTES:
            return _import_too_large_response()
        data = request.get_json(silent=True)
    else:
        if not request.files:
            return _validation_response(ConfigValidationError('请上传配置文件'))

        file = request.files.get('file')
        if not file:
            return _validation_response(ConfigValidationError('请上传配置文件'))

        try:
            raw = file.read(MAX_IMPORT_BYTES + 1)
            if len(raw) > MAX_IMPORT_BYTES:
                return _import_too_large_response()
            content = raw.decode('utf-8')
            data = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            return _validation_response(ConfigValidationError(f'文件格式错误: {e}'))

    try:
        entries = _prepare_import_entries(data)
    except ConfigValidationError as exc:
        return _validation_response(exc)

    # Validation of every item completes before the first write.  The explicit
    # transaction ensures a database failure cannot leave a partial import.
    _write_import_entries_atomically(entries)
    imported = [key for key, _ in entries]

    cfg = _safe_current_config(load_config())
    if cfg.get('run_mode', 'once') == 'once':
        _reload_scheduler_config()
        try:
            clear_scheduler_state()
        except Exception:
            pass
    else:
        _ensure_scheduler_started(cfg)

    if 'scan_config' in imported:
        try:
            import web.state as _state
            scanner = _state._scanner_module
            if scanner is not None:
                scanner.init_bridge()
                scanner.notify_scan_config_changed()
        except Exception:
            pass

    return jsonify({'ok': True, 'data': {'imported': imported}})


# ─────────────── 频道发现 API ───────────────

@config_bp.route('/api/discover', methods=['POST'])
def api_discover():
    """Scan subscription sources and discover available channels."""
    from engine.discovery import discover_channels
    try:
        result = discover_channels()
        return jsonify({'ok': True, 'data': result})
    except Exception as e:
        return jsonify({'ok': False, 'error': f'扫描失败: {e}'}), 500


@config_bp.route('/api/discover/merge', methods=['POST'])
def api_discover_merge():
    """Merge selected channels into the demo template."""
    from engine.discovery import merge_channels_into_demo
    data = request.get_json(silent=True)
    if not data or 'channels' not in data:
        return jsonify({'ok': False, 'error': '缺少 channels 字段'}), 400

    channels = data['channels']
    if not isinstance(channels, list):
        return jsonify({'ok': False, 'error': 'channels 应为列表'}), 400

    try:
        result = merge_channels_into_demo(channels)
        return jsonify({'ok': True, 'data': result})
    except Exception as e:
        return jsonify({'ok': False, 'error': f'合并失败: {e}'}), 500


# ─────────────── 多方案管理 API ───────────────

@config_bp.route('/api/profiles', methods=['GET'])
def api_list_profiles():
    """List all profile configurations."""
    import json
    raw = get_config_data('profiles')
    if raw:
        try:
            return jsonify({'ok': True, 'data': json.loads(raw)})
        except json.JSONDecodeError:
            pass
    return jsonify({'ok': True, 'data': [{'name': '默认', 'key': 'demo', 'description': '默认频道方案'}]})


@config_bp.route('/api/profiles', methods=['POST'])
def api_create_profile():
    """Create a new profile."""
    import json
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'ok': False, 'error': '请求数据无效'}), 400
    name = _sanitize_profile_name(data.get('name', ''))
    if not name:
        return jsonify({'ok': False, 'error': '方案名称无效（只允许中文、字母、数字、下划线、连字符，最长50字符）'}), 400
    description = data.get('description', '').strip()
    key = f'profile:{name}'
    raw = get_config_data('profiles')
    profiles = json.loads(raw) if raw else [{'name': '默认', 'key': 'demo', 'description': '默认频道方案'}]
    if any(p['key'] == key for p in profiles):
        return jsonify({'ok': False, 'error': '方案已存在'}), 400
    profiles.append({'name': name, 'key': key, 'description': description})
    set_config_data('profiles', json.dumps(profiles, ensure_ascii=False))
    if data.get('source') == 'copy':
        demo = get_config_data('demo')
        set_config_data(key, demo or '')
    else:
        set_config_data(key, f'{name},#genre#\n')
    return jsonify({'ok': True, 'data': {'key': key}})


@config_bp.route('/api/profiles/<name>', methods=['DELETE'])
def api_delete_profile(name):
    """Delete a profile."""
    import json
    name = _sanitize_profile_name(name)
    if not name:
        return jsonify({'ok': False, 'error': '方案名称无效'}), 400
    key = f'profile:{name}'
    if key == 'demo':
        return jsonify({'ok': False, 'error': '不能删除默认方案'}), 400
    raw = get_config_data('profiles')
    profiles = json.loads(raw) if raw else []
    profiles = [p for p in profiles if p['key'] != key]
    set_config_data('profiles', json.dumps(profiles, ensure_ascii=False))
    set_config_data(key, '')
    return jsonify({'ok': True})

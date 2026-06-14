# -*- coding: utf-8 -*-
"""
扫描配置桥接模块。
从 IPTV-Test 的 config_data 表读写扫描专用配置（key = 'scan_config'）。
替代 itv_scan 原始的 config.py + config.json 方案。
"""
import json

# ==================== 静态常量（不可运行时修改） ====================
HEAD_TIMEOUT = 1
STREAM_CHECK_TIMEOUT = 4
DEEP_CHECK_DURATION = 6
CONCURRENT_FAST = 50
CONCURRENT_DEEP = 8
GLOBAL_CONCURRENCY = 80
API_REQUEST_DELAY = 1.5
DAYDAYMAP_API_DELAY = 2.0
HEALTH_CHECK_INTERVAL = 120
FAIL_THRESHOLD = 2
AUTO_REFILL_QUAKE_SIZE = 10
STABILITY_THRESHOLD_NATIONAL = 60
STABILITY_THRESHOLD_LOCAL = 40
MIN_BANDWIDTH = 20
QUAKE_QUERY = 'body="/iptv/live/zh_cn.js"'
DAYDAYMAP_QUERY = 'body="/iptv/live/zh_cn.js"'
MIN_WIDTH, MIN_HEIGHT = 1280, 720
MAX_DELAY_MS = 3000
MAX_LINES_PER_CHANNEL = 10
C_SCAN_SEGMENT_TTL = 300  # C段缓存有效期（秒）

# ==================== 默认扫描配置 ====================
DEFAULT_SCAN_CONFIG = {
    "quake_api_keys": [],          # 多 key 列表（优先）
    "hunter_api_keys": [],
    "daydaymap_api_keys": [],
    "quake_api_key": "",           # 兼容旧单 key 格式
    "hunter_api_key": "",
    "daydaymap_api_key": "",
    "ddgs_enabled": False,
    "quake_size": 200,
    "operator": "",
    "province": "",
    "daily_full_update": True,
    "auto_refill": True,
    "update_time": "03:00",
    "update_days": [0, 1, 2, 3, 4, 5, 6],  # 0=周一, 6=周日
    "deep_concurrent": 15,
    "deep_batch_size": 50,
    "initialized": False,
    "enabled_platforms": [],
    "selected_provinces": [],
    "selected_cities": [],
    "strict_province_filter": False,
    "enable_c_scan": True,
    "c_scan_limit": 50,
    "c_scan_concurrent": 30,
    "c_segment_max_segments": 8,
    "c_segment_max_total_ips": 200,
    "detection_interval_minutes": 120,
    "deletion_threshold": 3,
}

_CONFIG_CACHE = None


def _normalize_key_list(cfg, platform, *legacy_single_names):
    """Normalize per-platform API keys into both list and single-key fields."""
    list_key = f'{platform}_api_keys'
    single_key = f'{platform}_api_key'

    merged = []
    raw_list = cfg.get(list_key, [])
    if isinstance(raw_list, list):
        merged.extend(raw_list)

    for name in (single_key, *legacy_single_names):
        value = cfg.get(name)
        if isinstance(value, str) and value.strip():
            merged.append(value)

    normalized = []
    seen = set()
    for key in merged:
        if not isinstance(key, str):
            continue
        value = key.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)

    cfg[list_key] = normalized
    cfg[single_key] = normalized[0] if normalized else ''


def _normalize_scan_config(raw_cfg):
    """Merge defaults and legacy aliases into a single canonical config."""
    cfg = dict(DEFAULT_SCAN_CONFIG)
    if isinstance(raw_cfg, dict):
        cfg.update(raw_cfg)

    _normalize_key_list(cfg, 'quake', 'quake_key')
    _normalize_key_list(cfg, 'hunter', 'hunter_key')
    _normalize_key_list(cfg, 'daydaymap', 'daydaymap_key')

    # Runtime compatibility for older scan paths that still read legacy names.
    cfg['quake_key'] = cfg.get('quake_api_key', '')
    cfg['hunter_key'] = cfg.get('hunter_api_key', '')
    cfg['daydaymap_key'] = cfg.get('daydaymap_api_key', '')
    return cfg


def get_scan_config():
    """从数据库读取扫描配置，合并默认值后返回 dict。"""
    global _CONFIG_CACHE
    from database import get_config_data
    raw = get_config_data('scan_config')
    if raw:
        try:
            loaded = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            loaded = {}
    else:
        loaded = {}
    cfg = _normalize_scan_config(loaded)
    _CONFIG_CACHE = cfg
    return cfg


def save_scan_config(cfg):
    """保存扫描配置到数据库。"""
    global _CONFIG_CACHE
    from database import set_config_data
    current = get_scan_config()
    merged = dict(current)
    if isinstance(cfg, dict):
        merged.update(cfg)
    normalized = _normalize_scan_config(merged)

    # Do not persist runtime-only compatibility aliases back to the database.
    persisted = dict(normalized)
    persisted.pop('quake_key', None)
    persisted.pop('hunter_key', None)
    persisted.pop('daydaymap_key', None)

    set_config_data('scan_config', json.dumps(persisted, ensure_ascii=False, indent=2))
    _CONFIG_CACHE = normalized


def get_scan_config_value(key, default=None):
    """快捷读取单个配置项（优先用缓存）。"""
    cfg = _CONFIG_CACHE or get_scan_config()
    return cfg.get(key, default)

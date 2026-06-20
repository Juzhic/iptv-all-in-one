# -*- coding: utf-8 -*-
"""
扫描配置桥接模块。
从 IPTV-Test 的 config_data 表读写扫描专用配置（key = 'scan_config'）。
替代 itv_scan 原始的 config.py + config.json 方案。
"""
import json
import re

# ==================== 静态常量（不可运行时修改） ====================
HEAD_TIMEOUT = 2
STREAM_CHECK_TIMEOUT = 4
DEEP_CHECK_DURATION = 6
CONCURRENT_FAST = 50
CONCURRENT_DEEP = 8
GLOBAL_CONCURRENCY = 80
API_REQUEST_DELAY = 1.5
DAYDAYMAP_API_DELAY = 2.0
FAIL_THRESHOLD = 2
AUTO_REFILL_QUAKE_SIZE = 10
STABILITY_THRESHOLD_NATIONAL = 60
STABILITY_THRESHOLD_LOCAL = 30
MIN_BANDWIDTH = 20
_IPTV_SEARCH_QUERY = 'body="/iptv/live/zh_cn.js" || body="1000.json?key=txiptv" || body="ZHGXTV" || body="jsmpeg-streamer" || title:"IPTV互动电视系统" || body="/iptv/live/" || title:"IPTV管理系统" || title:"酒店IPTV" || body="getChannelList" || body="EasyLive" || body="Hybroad" || body="udpxy" || body="tvheadend" || body="Xtream" && body="IPTV"'
QUAKE_QUERY = _IPTV_SEARCH_QUERY
HUNTER_QUERY = _IPTV_SEARCH_QUERY.replace('body=', 'web.body=').replace('title:', 'web.title:')
DAYDAYMAP_QUERY = _IPTV_SEARCH_QUERY
FOFA_QUERY = 'body="/iptv/live/zh_cn.js" || body="1000.json?key=txiptv" || body="ZHGXTV" || body="jsmpeg-streamer" || title="IPTV互动电视系统" || body="/iptv/live/" || title="IPTV管理系统" || title="酒店IPTV" || body="getChannelList" || body="EasyLive" || body="Hybroad" || body="udpxy" || body="tvheadend" || (body="Xtream" && body="IPTV")'
MIN_WIDTH, MIN_HEIGHT = 1280, 720
MAX_DELAY_MS = 2000

# ==================== 默认扫描配置 ====================
DEFAULT_SCAN_CONFIG = {
    "quake_api_keys": [],          # 多 key 列表（优先）
    "hunter_api_keys": [],
    "daydaymap_api_keys": [],
    "quake_api_key": "",           # 兼容旧单 key 格式
    "hunter_api_key": "",
    "daydaymap_api_key": "",
    "fofa_api_keys": [],
    "fofa_api_key": "",
    "fofa_email": "",
    "fofa_size": 200,
    "ddgs_enabled": False,
    "quake_size": 200,
    "operator": "",
    "province": "",
    "daily_full_update": True,
    "update_time": "03:00",
    "update_days": [0, 1, 2, 3, 4, 5, 6],  # 0=周一, 6=周日
    "deep_concurrent": 15,
    "deep_batch_size": 50,
    "enabled_platforms": [],
    "selected_provinces": [],
    "enable_c_scan": True,
    "c_scan_limit": 50,
    "c_segment_max_segments": 8,
    "c_segment_max_total_ips": 200,
    "detection_interval_minutes": 120,
    "detection_cycle_timeout_minutes": 30,
    "deletion_threshold": 3,
    "quality_history_keep_days": 90,
    "stable_channel_multiplier": 3,
    "resurrection_enabled": True,
    "resurrection_interval_hours": 24,
    "isp_intelligence_enabled": False,
    "hot_segment_min_channels": 3,
    "hot_segment_scan_limit": 200,
    "community_sources_enabled": False,
    "community_source_urls": [],
    "github_proxy": "",
    "scan_ports": [8080, 80, 443, 9981, 8888, 8000, 9090, 3000, 5000, 8443],
    "stability_weights": {
        "bandwidth": 0.35,
        "stutter": 0.25,
        "jitter": 0.20,
        "empty_rate": 0.15,
        "delay": 0.05,
    },
    "quality_thresholds": {
        "stability_high": 60,
        "stability_low": 30,
        "max_delay_ms": 2000,
        "min_bandwidth_kbps": 300,
    },
}

_CONFIG_CACHE = None
_CONFIG_CACHE_MTIME = None


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
    _normalize_key_list(cfg, 'fofa', 'fofa_key')

    # Runtime compatibility for older scan paths that still read legacy names.
    cfg['quake_key'] = cfg.get('quake_api_key', '')
    cfg['hunter_key'] = cfg.get('hunter_api_key', '')
    cfg['daydaymap_key'] = cfg.get('daydaymap_api_key', '')
    cfg['fofa_key'] = cfg.get('fofa_api_key', '')

    # 数值范围验证
    int_ranges = {
        'deep_concurrent': (1, 200),
        'deep_batch_size': (1, 500),
        'c_scan_limit': (1, 5000),
        'c_segment_max_segments': (1, 50),
        'c_segment_max_total_ips': (1, 5000),
        'detection_interval_minutes': (0, 10080),
        'detection_cycle_timeout_minutes': (1, 1440),
        'deletion_threshold': (1, 100),
        'quality_history_keep_days': (1, 365),
        'stable_channel_multiplier': (1, 10),
        'resurrection_interval_hours': (1, 720),
        'quake_size': (1, 10000),
        'fofa_size': (1, 10000),
        'hot_segment_min_channels': (1, 1000),
        'hot_segment_scan_limit': (1, 5000),
    }
    for key, (lo, hi) in int_ranges.items():
        val = cfg.get(key)
        if val is not None:
            try:
                cfg[key] = max(lo, min(hi, int(val)))
            except (TypeError, ValueError):
                cfg[key] = DEFAULT_SCAN_CONFIG.get(key)

    # update_time 格式验证
    update_time = cfg.get('update_time', '03:00')
    if not isinstance(update_time, str) or not re.match(r'^\d{2}:\d{2}$', update_time):
        cfg['update_time'] = '03:00'

    # update_days 范围验证
    update_days = cfg.get('update_days', [])
    if isinstance(update_days, list):
        cfg['update_days'] = [d for d in update_days if isinstance(d, int) and 0 <= d <= 6]

    return cfg


def get_scan_config():
    """从数据库读取扫描配置，合并默认值后返回 dict。使用缓存机制避免重复读取。"""
    global _CONFIG_CACHE, _CONFIG_CACHE_MTIME
    from database import get_config_data_with_mtime
    
    # 获取配置内容和更新时间
    raw, current_mtime = get_config_data_with_mtime('scan_config')
    
    # 如果配置未变化，直接返回缓存
    if _CONFIG_CACHE is not None and _CONFIG_CACHE_MTIME == current_mtime:
        return _CONFIG_CACHE
    
    # 配置有变化，重新解析
    if raw:
        try:
            loaded = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            loaded = {}
    else:
        loaded = {}
    
    cfg = _normalize_scan_config(loaded)
    _CONFIG_CACHE = cfg
    _CONFIG_CACHE_MTIME = current_mtime
    return cfg


def save_scan_config(cfg):
    """保存扫描配置到数据库。"""
    global _CONFIG_CACHE, _CONFIG_CACHE_MTIME
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
    persisted.pop('fofa_key', None)

    set_config_data('scan_config', json.dumps(persisted, ensure_ascii=False, indent=2))
    # 清除缓存，下次读取时会重新加载
    _CONFIG_CACHE = None
    _CONFIG_CACHE_MTIME = None


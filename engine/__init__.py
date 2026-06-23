# -*- coding: utf-8 -*-
"""
engine 包 — IPTV 测速引擎核心。
统一导出测试引擎、FFmpeg 分析、频道别名等公共接口。
"""
from engine.test_engine import (  # noqa: F401
    load_config,
    DEFAULT_CONFIG,
    resolve_output_update_time,
)
from engine.alias import (  # noqa: F401
    load_aliases,
    match_channel_name,
    get_cached_aliases,
    strip_quality_suffix,
    normalize_cctv_variant,
)
try:
    from engine.ffmpeg_test import (  # noqa: F401
        analyze_iptv_with_ffmpeg,
        register_timeout,
        clear_timeouts,
        set_ffmpeg_max_workers,
        set_ffmpeg_timeout,
        http_get,
        detect_non_live_media_url,
    )
except ImportError:
    pass

# -*- coding: utf-8 -*-
"""Scanner platforms package.

Re-exports public API for backward compatibility.
"""

from .shared import (
    QUALITY_QUERY_PROFILES,
    is_valid_stream_url,
    is_valid_channel_name,
    clean_url,
    remove_duplicate_national_channels,
    deduplicate,
    KeyDepletedError,
    _is_stop_requested,
    _retry_with_backoff,
    _handle_rate_limit,
    build_channel_entry,
    safe_decode_json,
    _decode_text,
    _normalize_stream_url,
    _make_channel_entry,
    _iter_channel_records,
    _record_to_channel,
    _parse_json_channels_payload,
    _parse_m3u_channels_payload,
    _parse_line_channels_payload,
    _parse_channels_payload,
    _extract_cache_key,
    _get_extract_cache,
    _set_extract_cache,
    _stats_add,
    _stats_set,
    _yield_stat_key,
    _build_yield_stat,
    classify_channel_full,
    normalize_cctv_name,
)

from .ip_extract import extract_channels_from_ip
from .collector import collect_all, _run_with_key_rotation
from .quake import quake_scan
from .fofa import fofa_scan
from .hunter import hunter_scan
from .daydaymap import daydaymap_scan
from .zhgx import zhgx_scan
from .jsmpeg import jsmpeg_streamer_scan
from .ddgs import ddgs_scan
from .tvheadend import tvheadend_scan, extract_tvheadend_channels, resolve_tvheadend_channel
from .iptv_interactive import iptv_interactive_scan, extract_iptv_interactive_channels, resolve_iptv_interactive_channel

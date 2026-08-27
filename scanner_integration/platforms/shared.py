# -*- coding: utf-8 -*-
"""platforms 公共模块：共享工具函数、常量、校验函数。"""

import asyncio
import base64
import json
import re
import time
from collections import OrderedDict
from urllib.parse import urljoin, urlparse

import aiohttp

from .. import config_bridge
from ..channel_utils import classify_channel_full, normalize_cctv_name
from ..logger_bridge import logger

# Quality-profile queries are intentionally separate from the editable main
# query list: they ensure each scan spends part of its budget on known IPTV
# interface families instead of letting broad rules crowd them out.
def _quality_query_profile(name, label, keywords):
    return {
        'name': name,
        'label': label,
        **config_bridge.build_search_queries({'search_keywords': keywords}),
    }


QUALITY_QUERY_PROFILES = (
    _quality_query_profile(
        'txiptv_live', 'TXIPTV 直播接口',
        ['/tsfile/live/ && key=txiptv', '/iptv/live/1000.json?key=txiptv'],
    ),
    _quality_query_profile(
        'live_interface', '标准直播接口',
        ['/iptv/live/zh_cn.js', '/iptv/live/1000.json'],
    ),
    _quality_query_profile(
        'zhgx', 'ZHGXTV 接口',
        ['/ZHGXTV/Public/json/live_interface.txt'],
    ),
    _quality_query_profile(
        'tvheadend', 'Tvheadend', ['title:Tvheadend'],
    ),
)

# ==================== KeyDepletedError ====================

class KeyDepletedError(Exception):
    """Raised when all API keys for a platform are exhausted (403)."""
    pass

# ==================== 重试和限流工具 ====================

def _is_stop_requested():
    from .. import scan_state
    return scan_state.stop_requested


async def _retry_with_backoff(coro_factory, max_retries=3, base_delay=1.0, max_delay=30.0):
    """带指数退避的重试装饰器。coro_factory 必须是返回协程的工厂函数。"""
    last_error = None
    for attempt in range(max_retries):
        try:
            return await coro_factory()
        except asyncio.TimeoutError as e:
            last_error = e
            if attempt < max_retries - 1:
                delay = min(base_delay * (2 ** attempt), max_delay)
                logger.debug(f"[Retry] 超时，{delay:.1f}秒后重试 (attempt {attempt + 1}/{max_retries})")
                await asyncio.sleep(delay)
        except aiohttp.ClientError as e:
            last_error = e
            if attempt < max_retries - 1:
                delay = min(base_delay * (2 ** attempt), max_delay)
                logger.debug(f"[Retry] 网络错误 {e}，{delay:.1f}秒后重试 (attempt {attempt + 1}/{max_retries})")
                await asyncio.sleep(delay)
        except KeyDepletedError:
            raise
        except Exception as e:
            last_error = e
            break
    raise last_error


async def _handle_rate_limit(response):
    """处理 429 Too Many Requests 响应，解析 Retry-After 头。"""
    if response.status == 429:
        retry_after = response.headers.get('Retry-After')
        if retry_after:
            try:
                delay = int(retry_after)
            except ValueError:
                delay = 60
        else:
            delay = 30
        logger.warning(f"[RateLimit] 触发限流，等待 {delay} 秒")
        await asyncio.sleep(delay)
        return True
    return False


# ==================== 频道条目工厂 ====================

def build_channel_entry(name, url, category, province='未知', city='', ip_province='', source_ip=None, **extra):
    """构建频道条目的工厂函数，统一字段格式。"""
    entry = {
        'name': name,
        'url': url,
        'category': category,
        'province': province or '未知',
        'city': city or '',
        'ip_province': ip_province or province or '未知',
        'name_province': province if province and province != '未知' else None,
        'source_ip': source_ip or '',
    }
    entry.update(extra)
    return entry


# ==================== JSON/文本解析工具 ====================

def safe_decode_json(raw):
    try:
        return json.loads(raw.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass
    try:
        return json.loads(raw.decode('gbk', errors='replace'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _decode_text(raw):
    for encoding in ('utf-8', 'gbk', 'gb2312'):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', errors='ignore')


# ==================== Yield 统计工具 ====================

def _stats_add(stats, key, value):
    if isinstance(stats, dict):
        stats[key] = stats.get(key, 0) + value


def _stats_set(stats, key, value):
    if isinstance(stats, dict):
        stats[key] = value


def _yield_stat_key(scope, platform_key, profile='', province=''):
    return ':'.join([
        scope or 'platform',
        platform_key or 'unknown',
        profile or 'base',
        province or 'all',
    ])


def _build_yield_stat(stat_key, scope, platform, profile, profile_label, province, stats, result_count):
    stats = stats if isinstance(stats, dict) else {}
    return {
        'stat_key': stat_key,
        'scope': scope or 'platform',
        'platform': platform or '',
        'profile': profile or '',
        'profile_label': profile_label or '',
        'province': province or '',
        'target_size': stats.get('target_size', 0),
        'api_items': stats.get('api_items', 0),
        'probed_hosts': stats.get('probed_hosts', 0),
        'extracted_channels': stats.get('extracted_channels', result_count),
        'c_segment_channels': stats.get('c_segment_channels', 0),
        'c_segment_segments': stats.get('c_segment_segments', 0),
        'c_segment_ips': stats.get('c_segment_ips', 0),
        'c_segment_cache_skipped': stats.get('c_segment_cache_skipped', 0),
        'c_segment_budget_skipped': stats.get('c_segment_budget_skipped', 0),
    }


# ==================== URL/频道名校验 ====================

# 检测 URL 中是否混入了 HTTP 响应头（如 WWW-Authenticate: Digest）
_HTTP_HEADER_URL_PATTERNS = (
    'www-authenticate', 'qop="auth', 'qop="none',
    'nonce="', 'opaque="', 'realm="', 'algorithm="md5',
    'algorithm="sha', 'stale="',
)


def is_valid_stream_url(url):
    """检查 URL 是否是合法的流地址（排除含 HTTP 认证头的畸形 URL）"""
    if not isinstance(url, str):
        return False
    lowered = url.lower()
    return not any(pat in lowered for pat in _HTTP_HEADER_URL_PATTERNS)


def is_valid_channel_name(name):
    if not isinstance(name, str) or not name.strip():
        return False
    s = name.strip()
    if len(s) > 60:
        return False
    if s.startswith(('{', '[', '<')):
        return False
    if re.search(r'^(data|javascript|vbscript):', s, re.I):
        return False
    lowered = s.lower()
    if any(kw in lowered for kw in ['data:text/plain', 'base64,', '"status":', 'null', 'undefined', 'session']):
        return False
    if any(k in lowered for k in ['api_request', 'metrics', 'prometheus', 'method=', 'status=']):
        return False
    if '::' in s or re.search(r'\.[A-Z]', s):
        return False
    # HTML 实体（如 &copy; &amp;）
    if re.search(r'&[a-z]+;', lowered) or re.search(r'&#\d+;', lowered):
        return False
    # 频道名不应含有的特殊字符
    if re.search(r'[\'"(){}<>\\|^~`]', s):
        return False
    # 纯 ASCII 字符（无中文）时进一步检查
    if not re.search(r'[一-鿿]', s):
        # 含冒号、分号、等号、斜杠 → 非频道名（如 ": Linux", "14:01:07"）
        if re.search(r'[:/;=]', s):
            return False
        # 纯 ASCII 且像普通英文单词（小写字母开头或全小写）→ 非频道名
        # 合法纯 ASCII 频道名通常是全大写缩写（CCTV、BBC）或含数字（CCTV1）
        if re.match(r'^[a-zA-Z][a-z]+$', s):
            return False
        # 纯数字
        if s.isdigit():
            return False
    # 常见系统输出模式
    if re.search(r'\d{2}:\d{2}:\d{2}', s):
        return False
    if re.search(r'up \d+ day', lowered):
        return False
    if re.search(r'mapping\(', lowered):
        return False
    return True


def clean_url(u):
    if not isinstance(u, str):
        return ""
    u = u.strip()
    if u.startswith(('http://', 'https://')):
        if is_valid_stream_url(u):
            return u
    if u.startswith('//'):
        return f"http:{u}"
    return ""


def remove_duplicate_national_channels(channels):
    nat_names = {c['name'] for c in channels if c.get('category') in ('央视频道', '央视付费频道', '卫视频道')}
    return [c for c in channels if c.get('category') in ('央视频道', '央视付费频道', '卫视频道') or c['name'] not in nat_names]


def deduplicate(sources):
    seen, uniq = set(), []
    for s in sources:
        if s['url'] not in seen:
            seen.add(s['url'])
            uniq.append(s)
    return uniq


# ==================== 文本响应解析 ====================

def _normalize_stream_url(stream_url, base_url):
    if not isinstance(stream_url, str):
        return ''
    value = stream_url.strip()
    if not value:
        return ''
    if value.startswith(('http://', 'https://')):
        full = value
    elif value.startswith('//'):
        full = f"http:{value}"
    else:
        full = urljoin(base_url + '/', value)
    return full if is_valid_stream_url(full) else ''


def _make_channel_entry(raw_name, stream_url, base_url, prov, city, source_ip):
    if not raw_name or not stream_url:
        return None
    full = _normalize_stream_url(stream_url, base_url)
    if not full:
        return None
    resolved, cat, final_prov, final_city = classify_channel_full(raw_name, prov, city)
    if resolved is None:
        return None
    return {
        'name': resolved,
        'url': full,
        'category': cat,
        'province': final_prov,
        'city': final_city,
        'ip_province': prov or final_prov,
        'name_province': final_prov if final_prov != '未知' else None,
        'source_ip': source_ip
    }


def _iter_channel_records(obj, depth=0):
    if depth > 3:
        return
    if isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict):
                yield item
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                yield {'name': item[0], 'url': item[1]}
            elif isinstance(item, (list, dict)):
                yield from _iter_channel_records(item, depth + 1)
        return
    if not isinstance(obj, dict):
        return

    name_keys = ('name', 'title', 'channelName', 'channel_name', 'tvg_name')
    url_keys = (
        'url', 'stream', 'stream_url', 'streamUrl', 'playUrl', 'play_url',
        'm3u8', 'path', 'uri'
    )
    has_name = any(k in obj for k in name_keys)
    has_url = any(k in obj for k in url_keys) or 'key' in obj
    if has_name and has_url:
        yield obj

    common_list_keys = (
        'data', 'channels', 'channel', 'list', 'rows', 'result', 'results',
        'items', 'live', 'lives'
    )
    for key in common_list_keys:
        if key in obj:
            yield from _iter_channel_records(obj[key], depth + 1)

    if depth <= 1:
        for key, value in obj.items():
            if isinstance(value, str) and isinstance(key, str):
                if value.startswith(('http://', 'https://', '/', 'rtmp://', 'udp://', 'rtp://')):
                    yield {'name': key, 'url': value}
            elif isinstance(value, (list, dict)) and key not in common_list_keys:
                yield from _iter_channel_records(value, depth + 1)


def _record_to_channel(record, base_url, prov, city, source_ip):
    name = (
        record.get('name') or record.get('title') or record.get('channelName')
        or record.get('channel_name') or record.get('tvg_name') or ''
    )
    stream_url = (
        record.get('url') or record.get('stream') or record.get('stream_url')
        or record.get('streamUrl') or record.get('playUrl') or record.get('play_url')
        or record.get('m3u8') or record.get('path') or record.get('uri') or ''
    )
    if not stream_url and record.get('key'):
        stream_url = f"/hls/{record.get('key')}/index.m3u8"
    return _make_channel_entry(name, stream_url, base_url, prov, city, source_ip)


def _parse_json_channels_payload(raw, base_url, prov, city, source_ip):
    decoded = safe_decode_json(raw)
    if decoded is None:
        return []
    channels = []
    seen_urls = set()
    for record in _iter_channel_records(decoded):
        channel = _record_to_channel(record, base_url, prov, city, source_ip)
        if not channel or channel['url'] in seen_urls:
            continue
        seen_urls.add(channel['url'])
        channels.append(channel)
        if len(channels) >= 500:
            break
    return channels


def _parse_m3u_channels_payload(text, base_url, prov, city, source_ip):
    channels = []
    current_name = None
    seen_urls = set()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith('#EXTINF:'):
            current_name = None
            tvg_match = re.search(r'tvg-name="([^"]*)"', line)
            if tvg_match:
                current_name = tvg_match.group(1).strip()
            name_match = re.search(r',(.+)$', line)
            if name_match:
                current_name = name_match.group(1).strip()
        elif current_name and not line.startswith('#'):
            channel = _make_channel_entry(current_name, line, base_url, prov, city, source_ip)
            current_name = None
            if not channel or channel['url'] in seen_urls:
                continue
            seen_urls.add(channel['url'])
            channels.append(channel)
            if len(channels) >= 500:
                break
    return channels


def _parse_line_channels_payload(text, base_url, prov, city, source_ip):
    channels = []
    seen_urls = set()
    for line in text.splitlines():
        line = line.strip().strip(';')
        if not line or line.startswith('#') or ',' not in line:
            continue
        name, stream_url = line.split(',', 1)
        channel = _make_channel_entry(name.strip(), stream_url.strip(), base_url, prov, city, source_ip)
        if not channel or channel['url'] in seen_urls:
            continue
        seen_urls.add(channel['url'])
        channels.append(channel)
        if len(channels) >= 500:
            break
    return channels


def _parse_channels_payload(raw, response_url, prov, city, source_ip):
    parsed = urlparse(response_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    channels = _parse_json_channels_payload(raw, base_url, prov, city, source_ip)
    if channels:
        return channels

    text = _decode_text(raw)
    if '#EXTINF:' in text:
        channels = _parse_m3u_channels_payload(text, base_url, prov, city, source_ip)
        if channels:
            return channels
    return _parse_line_channels_payload(text, base_url, prov, city, source_ip)


# ==================== Extract 缓存 ====================

_extract_cache = OrderedDict()
_EXTRACT_CACHE_TTL = 600
_EXTRACT_CACHE_MAX = 5000


def _extract_cache_key(ip, port, timeout):
    try:
        port = int(port)
    except (TypeError, ValueError):
        port = 8080
    mode = 'full' if timeout >= 5 else 'short'
    return (str(ip), port, mode)


def _get_extract_cache(key):
    item = _extract_cache.get(key)
    if not item:
        return None
    ts, value = item
    if time.time() - ts > _EXTRACT_CACHE_TTL:
        _extract_cache.pop(key, None)
        return None
    _extract_cache.move_to_end(key)
    return [dict(ch) for ch in value]


def _set_extract_cache(key, value):
    _extract_cache[key] = (time.time(), [dict(ch) for ch in (value or [])])
    _extract_cache.move_to_end(key)
    while len(_extract_cache) > _EXTRACT_CACHE_MAX:
        _extract_cache.popitem(last=False)

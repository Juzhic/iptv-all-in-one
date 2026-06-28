# platforms.py
import asyncio
import base64
import ipaddress
import json
import re
import random
import time
from collections import OrderedDict
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse
import aiohttp
import socket

from . import config_bridge
from .config_bridge import API_REQUEST_DELAY, DAYDAYMAP_API_DELAY, QUAKE_QUERY, HUNTER_QUERY, DAYDAYMAP_QUERY, FOFA_QUERY
from .channel_utils import is_blacklisted, normalize_cctv_name, classify_channel_full
from .network import global_sem, get_session
from .logger_bridge import logger

QUALITY_QUERY_PROFILES = [
    {
        'name': 'txiptv_live',
        'label': 'TXIPTV',
        'quake': '(body="/tsfile/live/" && body="key=txiptv") || body="/iptv/live/1000.json?key=txiptv"',
        'hunter': '(web.body="/tsfile/live/" && web.body="key=txiptv") || web.body="/iptv/live/1000.json?key=txiptv"',
        'daydaymap': '(body="/tsfile/live/" && body="key=txiptv") || body="/iptv/live/1000.json?key=txiptv"',
        'fofa': '(body="/tsfile/live/" && body="key=txiptv") || body="/iptv/live/1000.json?key=txiptv"',
    },
    {
        'name': 'live_interface',
        'label': '标准直播接口',
        'quake': 'body="/iptv/live/zh_cn.js" || body="/iptv/live/1000.json"',
        'hunter': 'web.body="/iptv/live/zh_cn.js" || web.body="/iptv/live/1000.json"',
        'daydaymap': 'body="/iptv/live/zh_cn.js" || body="/iptv/live/1000.json"',
        'fofa': 'body="/iptv/live/zh_cn.js" || body="/iptv/live/1000.json"',
    },
    {
        'name': 'zhgx',
        'label': 'ZHGXTV',
        'quake': 'body="ZHGXTV" || body="/ZHGXTV/Public/json/live_interface.txt"',
        'hunter': 'web.body="ZHGXTV" || web.body="/ZHGXTV/Public/json/live_interface.txt"',
        'daydaymap': 'body="ZHGXTV" || body="/ZHGXTV/Public/json/live_interface.txt"',
        'fofa': 'body="ZHGXTV" || body="/ZHGXTV/Public/json/live_interface.txt"',
    },
    {
        'name': 'jsmpeg',
        'label': 'JSMpeg',
        'quake': 'body="jsmpeg-streamer" || body="/streamer/list"',
        'hunter': 'web.body="jsmpeg-streamer" || web.body="/streamer/list"',
        'daydaymap': 'body="jsmpeg-streamer" || body="/streamer/list"',
        'fofa': 'body="jsmpeg-streamer" || body="/streamer/list"',
    },
    {
        'name': 'channel_api',
        'label': '频道 API',
        'quake': 'body="getChannelList" || body="/getChannelList" || body="/api/channels" || body="/channels" || body="/channel_list.json" || body="/api/live/channels" || body="/live/channels.json"',
        'hunter': 'web.body="getChannelList" || web.body="/getChannelList" || web.body="/api/channels" || web.body="/channels" || web.body="/channel_list.json" || web.body="/api/live/channels" || web.body="/live/channels.json"',
        'daydaymap': 'body="getChannelList" || body="/getChannelList" || body="/api/channels" || body="/channels" || body="/channel_list.json" || body="/api/live/channels" || body="/live/channels.json"',
        'fofa': 'body="getChannelList" || body="/getChannelList" || body="/api/channels" || body="/channels" || body="/channel_list.json" || body="/api/live/channels" || body="/live/channels.json"',
    },
    {
        'name': 'm3u_playlist',
        'label': 'M3U 播放列表',
        'quake': 'body="/playlist?profile=pass" || (body="#EXTM3U" && body="tvg-name")',
        'hunter': 'web.body="/playlist?profile=pass" || (web.body="#EXTM3U" && web.body="tvg-name")',
        'daydaymap': 'body="/playlist?profile=pass" || (body="#EXTM3U" && body="tvg-name")',
        'fofa': 'body="/playlist?profile=pass" || (body="#EXTM3U" && body="tvg-name")',
    },
    {
        'name': 'multicast_proxy',
        'label': '组播代理',
        'quake': 'body="udpxy" || body="/udpxy/chanlist" || body="/udp/chanlist" || body="/rtp/chanlist"',
        'hunter': 'web.body="udpxy" || web.body="/udpxy/chanlist" || web.body="/udp/chanlist" || web.body="/rtp/chanlist"',
        'daydaymap': 'body="udpxy" || body="/udpxy/chanlist" || body="/udp/chanlist" || body="/rtp/chanlist"',
        'fofa': 'body="udpxy" || body="/udpxy/chanlist" || body="/udp/chanlist" || body="/rtp/chanlist"',
    },
    {
        'name': 'tvheadend',
        'label': 'Tvheadend',
        'quake': 'body="tvheadend" || title:"Tvheadend" || body="/playlist?profile=pass"',
        'hunter': 'web.body="tvheadend" || web.title:"Tvheadend" || web.body="/playlist?profile=pass"',
        'daydaymap': 'body="tvheadend" || title:"Tvheadend" || body="/playlist?profile=pass"',
        'fofa': 'body="tvheadend" || title="Tvheadend" || body="/playlist?profile=pass"',
    },
    {
        'name': 'middleware_brand',
        'label': '中间件品牌',
        'quake': 'body="EasyLive" || body="Hybroad"',
        'hunter': 'web.body="EasyLive" || web.body="Hybroad"',
        'daydaymap': 'body="EasyLive" || body="Hybroad"',
        'fofa': 'body="EasyLive" || body="Hybroad"',
    },
    {
        'name': 'operator_playlist',
        'label': '运营商播放列表',
        'quake': 'body="/migu/playlist.m3u8" || body="/icntv/playlist.m3u8" || body="/migu/live/" || body="/icntv/live/"',
        'hunter': 'web.body="/migu/playlist.m3u8" || web.body="/icntv/playlist.m3u8" || web.body="/migu/live/" || web.body="/icntv/live/"',
        'daydaymap': 'body="/migu/playlist.m3u8" || body="/icntv/playlist.m3u8" || body="/migu/live/" || body="/icntv/live/"',
        'fofa': 'body="/migu/playlist.m3u8" || body="/icntv/playlist.m3u8" || body="/migu/live/" || body="/icntv/live/"',
    },
    {
        'name': 'xtream',
        'label': 'Xtream',
        'quake': '(body="Xtream" && body="IPTV")',
        'hunter': '(web.body="Xtream" && web.body="IPTV")',
        'daydaymap': '(body="Xtream" && body="IPTV")',
        'fofa': '(body="Xtream" && body="IPTV")',
    },
]

# ==================== 重试和限流工具 ====================
def _is_stop_requested():
    from . import scan_state
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


# ==================== 原 scanner.py 内容 ====================
def safe_decode_json(raw):
    try:
        return json.loads(raw.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass
    try:
        return json.loads(raw.decode('gbk', errors='replace'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


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
    }


def _decode_text(raw):
    for encoding in ('utf-8', 'gbk', 'gb2312'):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', errors='ignore')


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


async def extract_channels_from_ip(ip, port, session, prov="", city="", timeout=5):
    # SSRF protection: reject private/internal IPs
    try:
        addr = ipaddress.ip_address(ip)
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_multicast or addr.is_unspecified:
            return []
    except ValueError:
        return []

    cache_key = _extract_cache_key(ip, port, timeout)
    cached = _get_extract_cache(cache_key)
    if cached is not None:
        return cached

    candidate_urls = [
        f"http://{ip}:{port}/iptv/live/zh_cn.js",
        f"http://{ip}:{port}/iptv/live/1000.json?key=txiptv",
        f"http://{ip}:{port}/iptv/live/1000.json",
        f"http://{ip}:80/iptv/live/1000.json?key=txiptv",
        f"http://{ip}:8080/iptv/live/1000.json?key=txiptv",
        f"http://{ip}:{port}/ZHGXTV/Public/json/live_interface.txt",
        f"http://{ip}:{port}/streamer/list",
        f"http://{ip}:{port}/api/channels",
        f"http://{ip}:{port}/channels",
        f"http://{ip}:{port}/channel_list.json",
        f"http://{ip}:{port}/getChannelList",
        f"http://{ip}:{port}/api/live/channels",
        f"http://{ip}:{port}/live/channels.json",
        f"http://{ip}:{port}/playlist?profile=pass",
    ]
    async with global_sem:
        for url in candidate_urls:
            try:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(timeout),
                    allow_redirects=False
                ) as r:
                    if r.status != 200:
                        continue
                    result = _parse_channels_payload(await r.read(), str(r.url), prov, city, ip)
                    if result:
                        _set_extract_cache(cache_key, result)
                        return result
            except Exception as e:
                logger.debug(f"[extract] {ip}:{port} 失败: {e}")
                continue
    _set_extract_cache(cache_key, [])
    return []

def get_c_segment_ips(ip):
    parts = ip.split('.')
    if len(parts) != 4:
        return []
    return [f"{'.'.join(parts[:3])}.{i}" for i in range(1, 255)]

async def c_segment_scan(base_ip, port, session, limit=50):
    all_ips = get_c_segment_ips(base_ip)
    if len(all_ips) > limit:
        base_last = int(base_ip.split('.')[-1])
        neighbors = [ip for ip in all_ips if abs(int(ip.split('.')[-1]) - base_last) <= 10]
        others = [ip for ip in all_ips if ip not in neighbors]
        scanned = neighbors + random.sample(others, min(limit - len(neighbors), len(others)))
    else:
        scanned = all_ips
    logger.info(f"[C段] {base_ip}/24 扫描 {len(scanned)} 个IP")
    entries, cnt = [], 0
    for i in range(0, len(scanned), 50):
        batch = scanned[i:i+50]
        tasks = [extract_channels_from_ip(ip, port, session, timeout=3) for ip in batch]
        for lst in await asyncio.gather(*tasks, return_exceptions=True):
            if isinstance(lst, list) and lst:
                entries.extend(lst)
                cnt += 1
        if i + 50 < len(scanned):
            await asyncio.sleep(0.5)
    logger.info(f"[C段] 完成：{cnt}个IP有数据，{len(entries)}个频道")
    return entries

# C段缓存（带 TTL 和最大容量限制，使用 OrderedDict 保证 O(1) 操作）
class _TTLCache:
    def __init__(self, ttl=300, max_size=1000):
        self._cache = OrderedDict()
        self._ttl = ttl
        self._max_size = max_size

    def get(self, key):
        if key in self._cache:
            ts, val = self._cache[key]
            if time.time() - ts < self._ttl:
                self._cache.move_to_end(key)
                return val
            del self._cache[key]
        return None

    def set(self, key, val):
        if key in self._cache:
            self._cache.move_to_end(key)
        elif len(self._cache) >= self._max_size:
            self._cache.popitem(last=False)
        self._cache[key] = (time.time(), val)

_c_segment_cache = _TTLCache(ttl=300, max_size=1000)

async def smart_c_segment_scan(successful_ips, session):
    if not config_bridge.get_scan_config().get("enable_c_scan"):
        return []
    cs_limit = config_bridge.get_scan_config().get("c_scan_limit", 50)
    max_seg = config_bridge.get_scan_config().get("c_segment_max_segments", 8)
    max_total = config_bridge.get_scan_config().get("c_segment_max_total_ips", 200)
    segs = {}
    for ip, port in successful_ips:
        seg = '.'.join(ip.split('.')[:3])
        if seg not in segs:
            segs[seg] = (ip, port)
    now = time.time()
    fresh_segs = {}
    for seg, (ip, port) in segs.items():
        last = _c_segment_cache.get(seg)
        if last is None:
            fresh_segs[seg] = (ip, port)
            _c_segment_cache.set(seg, now)
        else:
            logger.debug(f"[C段] 跳过近期已扫描的 {seg}/24")
    segs = fresh_segs
    if len(segs) > max_seg:
        segs = dict(list(segs.items())[:max_seg])
    all_ip = []
    for ip, port in segs.values():
        ips = get_c_segment_ips(ip)
        if len(ips) > cs_limit:
            bl = int(ip.split('.')[-1])
            neighbors = [x for x in ips if abs(int(x.split('.')[-1]) - bl) <= 10]
            others = [x for x in ips if x not in neighbors]
            scanned = neighbors + random.sample(others, min(cs_limit - len(neighbors), len(others)))
        else:
            scanned = ips
        all_ip.extend((x, port) for x in scanned)
    if len(all_ip) > max_total:
        logger.info(f"[C段] 限制IP总数 {max_total}")
        all_ip = random.sample(all_ip, max_total)
    logger.info(f"[C段] 最终扫描 {len(all_ip)} 个IP")
    entries, cnt = [], 0
    for i in range(0, len(all_ip), 50):
        batch = all_ip[i:i+50]
        tasks = [extract_channels_from_ip(ip, p, session, timeout=3) for ip, p in batch]
        for lst in await asyncio.gather(*tasks, return_exceptions=True):
            if isinstance(lst, list) and lst:
                entries.extend(lst)
                cnt += 1
        if i + 50 < len(all_ip):
            await asyncio.sleep(0.5)
    seen = set()
    uniq = []
    for e in entries:
        if e['url'] not in seen:
            seen.add(e['url'])
            uniq.append(e)
    logger.info(f"[C段] 发现 {len(uniq)} 个新频道")
    return uniq

# ==================== 原 platforms.py 内容（优化后） ====================
PLATFORM_TIMEOUT = 180

async def quake_scan(api_key=None, query=None, target_size=None, session=None, stats=None):
    if api_key is None: api_key = config_bridge.get_scan_config().get("quake_key", "")
    if not api_key:
        logger.warning("[Quake] 未配置 API Key，跳过")
        return []
    if query is None:
        logger.warning("[Quake] 未提供搜索查询条件，跳过")
        return []
    if target_size is None: target_size = config_bridge.get_scan_config().get("quake_size", 200)
    _stats_set(stats, 'target_size', target_size)
    if session is None: session = get_session(limit=30, force_close=True)
    BATCH_SIZE = 50
    collected_entries, collected_success = [], []
    for start in range(0, target_size, BATCH_SIZE):
        if _is_stop_requested():
            logger.info("[Quake] 检测到中止请求，停止扫描")
            break
        size = min(BATCH_SIZE, target_size - start)
        try:
            await asyncio.sleep(API_REQUEST_DELAY * 0.5)
            async with session.post(
                "https://quake.360.net/api/v3/search/quake_service",
                headers={"X-QuakeToken": api_key, "Content-Type": "application/json"},
                json={"query": query, "start": start, "size": size, "latest": True},
                timeout=aiohttp.ClientTimeout(total=15)
            ) as r:
                if r.status == 200:
                    j = await r.json()
                    if j.get("code") == 0:
                        items = j.get("data", [])
                        if not items: break
                        _stats_add(stats, 'api_items', len(items))
                        _stats_add(stats, 'probed_hosts', len(items))
                        logger.info(f"[Quake] 获取 {start}~{start+len(items)} 条")
                        async def f(item):
                            ch = await extract_channels_from_ip(
                                item.get("ip"), item.get("port", 8080), session,
                                (item.get("province", "") or (item.get("location", {}) or {}).get("province_cn", "")), (item.get("city", "") or (item.get("location", {}) or {}).get("city_cn", ""))
                            )
                            if ch:
                                collected_success.append((item.get("ip"), item.get("port", 8080)))
                            return ch
                        for lst in await asyncio.gather(*[f(it) for it in items]):
                            if lst: collected_entries.extend(lst)
                        if len(items) < size: break
                elif r.status == 403:
                    raise KeyDepletedError("Quake key 积分耗尽")
                else:
                    logger.warning(f"[Quake] 请求失败 HTTP {r.status}")
                    break
        except KeyDepletedError:
            raise  # 让 key 耗尽冒泡到 _run_with_key_rotation 触发轮换
        except asyncio.TimeoutError:
            logger.warning(f"[Quake] 批次 {start} 超时")
            break
        except Exception as e:
            logger.warning(f"[Quake] 批次 {start} 失败: {e}")
            break
    logger.info(f"[Quake] 总共提取频道: {len(collected_entries)}")
    if config_bridge.get_scan_config().get("enable_c_scan") and collected_success:
        c_entries = await smart_c_segment_scan(collected_success, session)
        _stats_add(stats, 'c_segment_channels', len(c_entries))
        collected_entries.extend(c_entries)
    _stats_set(stats, 'extracted_channels', len(collected_entries))
    return collected_entries

async def fofa_scan(api_key=None, query=None, target_size=None, session=None, stats=None):
    if api_key is None: api_key = config_bridge.get_scan_config().get("fofa_key", "")
    if not api_key:
        logger.warning("[Fofa] 未配置 API Key，跳过")
        return []
    if query is None:
        logger.warning("[Fofa] 未提供搜索查询条件，跳过")
        return []
    email = config_bridge.get_scan_config().get("fofa_email", "")
    if not email:
        logger.warning("[Fofa] 未配置 email，跳过")
        return []
    if target_size is None: target_size = config_bridge.get_scan_config().get("fofa_size", 200)
    _stats_set(stats, 'target_size', target_size)
    if session is None: session = get_session(limit=30, force_close=True)
    BATCH_SIZE = 50
    collected_entries, collected_success = [], []
    qbase64 = base64.urlsafe_b64encode(query.encode()).decode().rstrip('=')
    page = 1
    for start in range(0, target_size, BATCH_SIZE):
        if _is_stop_requested():
            logger.info("[Fofa] 检测到中止请求，停止扫描")
            break
        size = min(BATCH_SIZE, target_size - start)
        try:
            await asyncio.sleep(API_REQUEST_DELAY * 0.5)
            async def _req():
                return await session.get(
                    "https://fofa.info/api/v1/search/all",
                    params={
                        "email": email,
                        "key": api_key,
                        "qbase64": qbase64,
                        "size": size,
                        "page": page,
                        "fields": "ip,port,host,title,region"
                    },
                    timeout=aiohttp.ClientTimeout(total=15)
                )
            r = await _retry_with_backoff(_req)
            async with r:
                if r.status == 200:
                    j = await r.json()
                    if j.get("error") is False:
                        results = j.get("results", [])
                        if not results: break
                        _stats_add(stats, 'api_items', len(results))
                        logger.info(f"[Fofa] 第{page}页，{len(results)} 条")
                        items = []
                        for row in results:
                            if not isinstance(row, (list, tuple)) or len(row) < 4:
                                continue
                            ip = str(row[0]).split(':')[0] if row[0] else ''
                            try:
                                port = int(row[1]) if row[1] else 8080
                            except (TypeError, ValueError):
                                port = 8080
                            if not ip:
                                continue
                            province = str((row[4] if len(row) > 4 else row[3]) or '')
                            items.append({
                                "ip": ip, "port": port,
                                "province": province,
                                "city": ''
                            })
                        _stats_add(stats, 'probed_hosts', len(items))
                        async def f(item):
                            ch = await extract_channels_from_ip(
                                item["ip"], item["port"], session,
                                item["province"], item["city"]
                            )
                            if ch:
                                collected_success.append((item["ip"], item["port"]))
                            return ch
                        for lst in await asyncio.gather(*[f(it) for it in items]):
                            if lst: collected_entries.extend(lst)
                        if len(results) < size: break
                        page += 1
                    else:
                        logger.warning(f"[Fofa] API 返回错误: {j.get('errmsg')}")
                        break
                elif r.status == 403:
                    raise KeyDepletedError("Fofa key 积分耗尽")
                else:
                    logger.warning(f"[Fofa] 请求失败 HTTP {r.status}")
                    break
        except KeyDepletedError:
            raise
        except asyncio.TimeoutError:
            logger.warning(f"[Fofa] 第{page}页超时")
            break
        except Exception as e:
            logger.warning(f"[Fofa] 第{page}页失败: {e}")
            break
    logger.info(f"[Fofa] 总共提取频道: {len(collected_entries)}")
    if config_bridge.get_scan_config().get("enable_c_scan") and collected_success:
        c_entries = await smart_c_segment_scan(collected_success, session)
        _stats_add(stats, 'c_segment_channels', len(c_entries))
        collected_entries.extend(c_entries)
    _stats_set(stats, 'extracted_channels', len(collected_entries))
    return collected_entries

async def hunter_scan(api_key, query, target_size, session=None, stats=None):
    if not api_key:
        logger.warning("[Hunter] 未配置 API Key，跳过")
        return []
    if session is None:
        session = get_session(limit=30, force_close=True)
    if target_size is None:
        target_size = config_bridge.get_scan_config().get("hunter_size", config_bridge.get_scan_config().get("quake_size", 200))
    MAX_PAGE_SIZE = 10
    _stats_set(stats, 'target_size', target_size)
    collected_entries = []
    collected_success = []
    page = 1
    BATCH_SIZE = MAX_PAGE_SIZE
    fetched_items = 0
    while fetched_items < target_size:
        if _is_stop_requested():
            logger.info("[Hunter] 检测到中止请求，停止扫描")
            break
        remaining = target_size - fetched_items
        size = min(BATCH_SIZE, remaining)
        page_size = max(1, min(MAX_PAGE_SIZE, size))
        try:
            await asyncio.sleep(API_REQUEST_DELAY * 0.5)
            qb = base64.urlsafe_b64encode(query.encode()).decode().rstrip('=')
            logger.info(f"[Hunter] 请求 page={page}, page_size={page_size}")
            async with session.get(
                "https://hunter.qianxin.com/openApi/search",
                params={
                    "api-key": api_key,
                    "search": qb,
                    "page": page,
                    "page_size": page_size,
                    "is_web": 1
                },
                timeout=aiohttp.ClientTimeout(total=15)
            ) as r:
                if r.status == 200:
                    j = await r.json()
                    if j.get("code") in (200, 0):
                        data = j.get("data") or {}
                        items = data.get("arr") or []
                        if not items:
                            break
                        fetched_items += len(items)
                        _stats_add(stats, 'api_items', len(items))
                        _stats_add(stats, 'probed_hosts', len(items))
                        logger.info(f"[Hunter] 第{page}页，{len(items)} 条")
                        async def f(item):
                            ch = await extract_channels_from_ip(
                                item.get("ip"), item.get("port", 8080), session,
                                (item.get("province", "") or (item.get("location", {}) or {}).get("province_cn", "")), (item.get("city", "") or (item.get("location", {}) or {}).get("city_cn", ""))
                            )
                            if ch:
                                collected_success.append((item.get("ip"), item.get("port", 8080)))
                            return ch
                        for lst in await asyncio.gather(*[f(it) for it in items]):
                            if lst:
                                collected_entries.extend(lst)
                        if len(items) < page_size:
                            break
                        page += 1
                    else:
                        logger.warning(f"[Hunter] API 返回错误: {j.get('message')}, 完整响应: {j}")
                        break
                elif r.status == 403:
                    raise KeyDepletedError("Hunter key 积分耗尽")
                else:
                    logger.warning(f"[Hunter] 请求失败 HTTP {r.status}, 响应: {await r.text()}")
                    break
        except KeyDepletedError:
            raise  # 让 key 耗尽冒泡到 _run_with_key_rotation 触发轮换
        except asyncio.TimeoutError:
            logger.warning(f"[Hunter] 第{page}页超时")
            break
        except Exception as e:
            logger.warning(f"[Hunter] 批次 {page} 失败: {e}")
            break
    logger.info(f"[Hunter] 总共提取频道: {len(collected_entries)}")
    if config_bridge.get_scan_config().get("enable_c_scan") and collected_success:
        c_entries = await smart_c_segment_scan(collected_success, session)
        _stats_add(stats, 'c_segment_channels', len(c_entries))
        collected_entries.extend(c_entries)
    _stats_set(stats, 'extracted_channels', len(collected_entries))
    return collected_entries

async def daydaymap_scan(api_key, query, target_size, session=None, stats=None):
    if not api_key:
        logger.warning("[DayDayMap] 未配置 API Key，跳过")
        return []
    if session is None: session = get_session(limit=30, force_close=True)
    if target_size is None: target_size = config_bridge.get_scan_config().get("daydaymap_size", 200)
    _stats_set(stats, 'target_size', target_size)
    BATCH_SIZE = 50
    all_items = []
    headers = {"api-key": api_key, "Content-Type": "application/json"}
    keyword_base64 = base64.b64encode(query.encode()).decode()
    page = 1
    max_pages = max(1, (target_size + BATCH_SIZE - 1) // BATCH_SIZE)
    while len(all_items) < target_size and page <= max_pages:
        if _is_stop_requested():
            logger.info("[DayDayMap] 检测到中止请求，停止扫描")
            break
        size = min(BATCH_SIZE, target_size - len(all_items))
        post_data = {"page": page, "page_size": size, "keyword": keyword_base64}
        try:
            await asyncio.sleep(DAYDAYMAP_API_DELAY * 0.5)
            async with session.post(
                "https://www.daydaymap.com/api/v1/raymap/search/all",
                headers=headers, json=post_data,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("code") == 200:
                        inner = data.get("data", {})
                        items = inner.get("list", [])
                        if not items: break
                        _stats_add(stats, 'api_items', len(items))
                        logger.info(f"[DayDayMap] 第{page}页，{len(items)} 条")
                        for item in items:
                            ip = item.get("ip")
                            if ip:
                                try:
                                    port = int(item.get("port", 8080))
                                except (TypeError, ValueError):
                                    port = 8080  # 脏数据跳过端口转换，用默认值而非中断分页
                                all_items.append({
                                    "ip": ip, "port": port,
                                    "province": (item.get("province", "") or (item.get("location", {}) or {}).get("province_cn", "")), "city": (item.get("city", "") or (item.get("location", {}) or {}).get("city_cn", ""))
                                })
                        _stats_set(stats, 'probed_hosts', len(all_items))
                        if len(items) < size: break
                        page += 1
                    else:
                        logger.warning(f"[DayDayMap] API 返回错误: {data.get('message')}")
                        break
                elif resp.status == 403:
                    raise KeyDepletedError("DayDayMap key 积分耗尽")
                else:
                    logger.warning(f"[DayDayMap] 请求失败 HTTP {resp.status}")
                    break
        except KeyDepletedError:
            raise  # 让 key 耗尽冒泡到 _run_with_key_rotation 触发轮换
        except asyncio.TimeoutError:
            logger.warning(f"[DayDayMap] 第{page}页超时")
            break
        except Exception as e:
            logger.warning(f"[DayDayMap] 批次 {page} 失败: {e}")
            break
    if not all_items: return []
    logger.info(f"[DayDayMap] 获取到 {len(all_items)} 个IP")
    all_items = all_items[:target_size]
    entries, success = [], []
    async def f(item):
        ch = await extract_channels_from_ip(item["ip"], item["port"], session, item["province"], item["city"])
        if ch: success.append((item["ip"], item["port"]))
        return ch
    for lst in await asyncio.gather(*[f(it) for it in all_items]):
        if lst: entries.extend(lst)
    if config_bridge.get_scan_config().get("enable_c_scan") and success:
        c_entries = await smart_c_segment_scan(success, session)
        _stats_add(stats, 'c_segment_channels', len(c_entries))
        entries.extend(c_entries)
    _stats_set(stats, 'extracted_channels', len(entries))
    return entries

async def zhgx_scan(size=10, session=None):
    ips = set()
    quake_key = config_bridge.get_scan_config().get("quake_key")
    if quake_key:
        await asyncio.sleep(API_REQUEST_DELAY)
        try:
            if session is None: session = get_session(limit=30, force_close=True)
            async with session.post(
                "https://quake.360.net/api/v3/search/quake_service",
                headers={"X-QuakeToken": quake_key, "Content-Type": "application/json"},
                json={"query": 'body="ZHGXTV"', "start": 0, "size": size, "latest": True},
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status == 200:
                    j = await resp.json()
                    if j.get("code") == 0:
                        for item in j.get("data", []):
                            ip = item.get("ip"); port = item.get("port", 80)
                            if ip: ips.add((ip, port))
        except Exception as e:
            logger.debug(f"[ZHGX] Quake 查询失败: {e}")
    hunter_key = config_bridge.get_scan_config().get("hunter_key")
    if hunter_key:
        await asyncio.sleep(API_REQUEST_DELAY)
        try:
            qb = base64.urlsafe_b64encode('web.body="ZHGXTV"'.encode()).decode().rstrip('=')
            if session is None: session = get_session(limit=30, force_close=True)
            async with session.get(
                "https://hunter.qianxin.com/openApi/search",
                params={"api-key": hunter_key, "search": qb, "page": 1, "page_size": min(10, size), "is_web": 1},
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status == 200:
                    j = await resp.json()
                    if j.get("code") in (200, 0):
                        for item in j.get("data", {}).get("arr", []):
                            ip = item.get("ip"); port = item.get("port", 80)
                            if ip: ips.add((ip, port))
        except Exception as e:
            logger.debug(f"[ZHGX] Hunter 查询失败: {e}")
    if not ips:
        logger.info("[ZHGX] 未发现IP")
        return []
    logger.info(f"[ZHGX] {len(ips)} IP")
    entries, success = [], []
    if session is None:
        session = get_session(limit=30, force_close=True)
    async def f(ip, port):
        base = f"http://{ip}:{port}"
        async with global_sem:
            try:
                async with session.get(f"{base}/ZHGXTV/Public/json/live_interface.txt", timeout=aiohttp.ClientTimeout(5)) as r:
                    if r.status == 200:
                        text = await r.text()
                        chs = []
                        for line in text.splitlines():
                            line = line.strip()
                            if not line or ',' not in line: continue
                            parts = line.split(',', 1)
                            if len(parts) < 2: continue
                            name, url_part = parts[0].strip(), parts[1].strip()
                            if not name or not url_part: continue
                            if url_part.startswith('http://') or url_part.startswith('https://'):
                                full = url_part
                            else:
                                full = url_part if url_part.startswith('http') else urljoin(base + '/', url_part)
                            if not is_valid_stream_url(full):
                                continue
                            resolved, cat, final_prov, final_city = classify_channel_full(name)
                            if resolved is None:
                                continue
                            chs.append({
                                'name': resolved, 'url': full, 'category': cat,
                                'province': final_prov,
                                'city': final_city,
                                'ip_province': final_prov,
                                'name_province': final_prov if final_prov != '未知' else None,
                                'source_ip': ip
                            })
                        if chs: success.append((ip, port))
                        return chs
            except Exception as e:
                logger.debug(f"[ZHGX] {ip}:{port} 失败: {e}")
        return []
    for lst in await asyncio.gather(*[f(ip, port) for ip, port in ips]):
        if _is_stop_requested():
            logger.info("[ZHGX] 检测到中止请求，停止扫描")
            break
        if lst: entries.extend(lst)
    if config_bridge.get_scan_config().get("enable_c_scan") and success:
        entries.extend(await smart_c_segment_scan(success, session))
    return entries

# 修正后的 JSMpeg 扫描函数（全国、最近一个月）
async def jsmpeg_streamer_scan(province=None, operator=None, size=30, session=None):
    logger.info(f"[JSMpeg] 开始扫描, province={province}, operator={operator}, size={size}")
    if session is None:
        session = get_session(limit=30, force_close=True)
    quake_key = config_bridge.get_scan_config().get("quake_key")
    hunter_key = config_bridge.get_scan_config().get("hunter_key")
    ddm_key = config_bridge.get_scan_config().get("daydaymap_api_key")

    collected_ips = {}  # (ip, port) -> 来源平台名（Quake/Hunter/DayDayMap）

    one_month_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    base_query = 'body="jsmpeg-streamer"'
    op_cond = f' AND isp="{operator}"' if operator else ''
    hunter_prov_cond = f' && ip.province=="{province}"' if province else ''
    ddm_prov_cond = f' && province=="{province}"' if province else ''
    quake_prov_cond = f' AND province="{province}"' if province else ''

    hunter_time_cond = f' && after="{one_month_ago}"'
    # 注意：Quake 不再使用 after 条件，避免高级会员限制

    if quake_key:
        try:
            # 去掉 after 时间条件
            query = f'{base_query}{quake_prov_cond}{op_cond}'
            logger.info(f"[JSMpeg] Quake 查询语句: {query}")
            async with session.post(
                "https://quake.360.net/api/v3/search/quake_service",
                headers={"X-QuakeToken": quake_key, "Content-Type": "application/json"},
                json={"query": query, "start": 0, "size": size, "latest": True},
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status == 200:
                    j = await resp.json()
                    if j.get("code") == 0:
                        items = j.get("data", [])
                        for item in items:
                            ip = item.get("ip")
                            port = item.get("port", 8080)
                            if ip and (ip, port) not in collected_ips:
                                collected_ips[(ip, port)] = 'Quake 360'
                        logger.info(f"[JSMpeg] Quake 发现 {len(items)} 个IP")
                    else:
                        logger.warning(f"[JSMpeg] Quake 返回错误: {j.get('message')}")
        except Exception as e:
            logger.warning(f"[JSMpeg] Quake 查询失败: {e}")

    if hunter_key and len(collected_ips) < size:
        try:
            query = f'web.body="jsmpeg-streamer"{hunter_prov_cond}{hunter_time_cond}{op_cond}'
            logger.info(f"[JSMpeg] Hunter 查询语句: {query}")
            qb = base64.urlsafe_b64encode(query.encode()).decode().rstrip('=')
            hunter_page_size = min(10, size)
            async with session.get(
                "https://hunter.qianxin.com/openApi/search",
                params={"api-key": hunter_key, "search": qb, "page": 1, "page_size": hunter_page_size, "is_web": 1},
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status == 200:
                    j = await resp.json()
                    if j.get("code") in (200, 0):
                        data = j.get("data")
                        if data is None:
                            items = []
                        else:
                            items = data.get("arr", [])
                        for item in items:
                            ip = item.get("ip")
                            port = item.get("port", 8080)
                            if ip and (ip, port) not in collected_ips:
                                collected_ips[(ip, port)] = 'Hunter'
                        logger.info(f"[JSMpeg] Hunter 发现 {len(items)} 个IP")
                    else:
                        logger.warning(f"[JSMpeg] Hunter 返回错误: {j.get('message')}")
                elif resp.status == 403:
                    raise KeyDepletedError("Hunter key 积分耗尽")
                else:
                    logger.warning(f"[JSMpeg] Hunter HTTP {resp.status}")
        except KeyDepletedError:
            raise
        except Exception as e:
            logger.warning(f"[JSMpeg] Hunter 查询失败: {e}")

    if ddm_key and len(collected_ips) < size:
        try:
            query = f'body="jsmpeg-streamer"{ddm_prov_cond}{op_cond}'
            logger.info(f"[JSMpeg] DayDayMap 查询语句: {query}")
            keyword_base64 = base64.b64encode(query.encode()).decode()
            async with session.post(
                "https://www.daydaymap.com/api/v1/raymap/search/all",
                headers={"api-key": ddm_key, "Content-Type": "application/json"},
                json={"page": 1, "page_size": min(size, 100), "keyword": keyword_base64},
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("code") == 200:
                        items = data.get("data", {}).get("list", [])
                        for item in items:
                            ip = item.get("ip")
                            if ip:
                                port = int(item.get("port", 8080))
                                if (ip, port) not in collected_ips:
                                    collected_ips[(ip, port)] = 'DayDayMap'
                        logger.info(f"[JSMpeg] DayDayMap 发现 {len(items)} 个IP")
                    else:
                        logger.warning(f"[JSMpeg] DayDayMap 返回错误: {data.get('message')}")
                elif resp.status == 403:
                    raise KeyDepletedError("DayDayMap key 积分耗尽")
                else:
                    logger.warning(f"[JSMpeg] DayDayMap HTTP {resp.status}")
        except KeyDepletedError:
            raise
        except Exception as e:
            logger.warning(f"[JSMpeg] DayDayMap 查询失败: {e}")

    if not collected_ips:
        logger.info("[JSMpeg] 未发现服务器")
        return []

    logger.info(f"[JSMpeg] 共发现 {len(collected_ips)} 个潜在服务器，开始提取频道列表")
    entries = []
    async def process_server(ip, port, source):
        base_url = f"http://{ip}:{port}"
        list_urls = [
            f"{base_url}/streamer/list",
            f"{base_url}/list",
            f"{base_url}/api/channels",
            f"{base_url}/channels.json"
        ]
        for list_url in list_urls:
            try:
                async with session.get(list_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                    if not isinstance(data, list):
                        if isinstance(data, dict) and "channels" in data:
                            data = data["channels"]
                        else:
                            continue
                    chs = []
                    for ch_info in data:
                        key = ch_info.get("key")
                        raw_name = ch_info.get("name")
                        if not key or not raw_name:
                            continue
                        stream_url = f"{base_url}/hls/{key}/index.m3u8"
                        norm_name = normalize_cctv_name(raw_name)
                        resolved_name, cat, final_prov, final_city = classify_channel_full(norm_name, province)
                        if resolved_name is None:
                            continue
                        chs.append({
                            'name': resolved_name,
                            'url': stream_url,
                            'category': cat,
                            'province': final_prov,
                            'city': final_city,
                            'ip_province': province or '',
                            'name_province': final_prov if final_prov != '未知' else None,
                            'source_ip': ip,
                            'scan_source': source
                        })
                    if chs:
                        logger.debug(f"[JSMpeg] 从 {ip}:{port} 的 {list_url} 提取到 {len(chs)} 个频道")
                        return chs
            except Exception as e:
                logger.debug(f"[JSMpeg] 尝试 {list_url} 失败: {e}")
                continue
        return []

    tasks = [process_server(ip, port, source) for (ip, port), source in collected_ips.items()]
    for result in await asyncio.gather(*tasks, return_exceptions=True):
        if _is_stop_requested():
            logger.info("[JSMpeg] 检测到中止请求，停止扫描")
            break
        if isinstance(result, list) and result:
            entries.extend(result)
    logger.info(f"[JSMpeg] 扫描完成，提取到 {len(entries)} 个频道")
    return entries

# DuckDuckGo 搜索
_DDGS_CLASS = None
_DDGS_IMPORT_ATTEMPTED = False


def _get_ddgs_class():
    global _DDGS_CLASS, _DDGS_IMPORT_ATTEMPTED
    if not _DDGS_IMPORT_ATTEMPTED:
        _DDGS_IMPORT_ATTEMPTED = True
        try:
            from ddgs import DDGS as ddgs_class
            _DDGS_CLASS = ddgs_class
        except ImportError:
            _DDGS_CLASS = None
    return _DDGS_CLASS

async def ddgs_scan(query=None, target_size=30, session=None):
    ddgs_class = _get_ddgs_class()
    if ddgs_class is None:
        logger.warning("[DDGS] ddgs 库未安装，跳过扫描")
        return []
    if session is None:
        session = get_session(limit=30, force_close=True)
    if not query:
        query = '("iptv/live/zh_cn.js" OR "streamer/list" OR "1000.json") AND (hotel OR iptv)'
    try:
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(
            None, lambda: list(ddgs_class().text(query, max_results=target_size))
        )
        if not results:
            logger.info("[DDGS] 未搜索到结果")
            return []
        logger.info(f"[DDGS] 获取到 {len(results)} 个结果")
        domains = set()
        for item in results:
            url = item.get("href", "")
            if not url:
                continue
            parsed = urlparse(url)
            domain = parsed.netloc
            if domain:
                domains.add(domain)
        logger.info(f"[DDGS] 获取到 {len(domains)} 个唯一域名")
        loop = asyncio.get_running_loop()
        ip_set = set()
        for domain in domains:
            try:
                ips = await loop.getaddrinfo(domain, None, family=socket.AF_INET)
                for ip_info in ips:
                    ip = ip_info[4][0]
                    ip_set.add(ip)
            except Exception as e:
                logger.debug(f"[DDGS] DNS 解析 {domain} 失败: {e}")
        logger.info(f"[DDGS] 解析出 {len(ip_set)} 个 IP")
        entries = []
        success_ips = []
        for ip in ip_set:
            if _is_stop_requested():
                logger.info("[DDGS] 检测到中止请求，停止扫描")
                break
            for port in config_bridge.get_scan_config().get(
                    'scan_ports', [8080, 80, 443, 9981, 8888, 8000, 9090, 3000, 5000, 8443]):
                ch = await extract_channels_from_ip(ip, port, session, timeout=3)
                if ch:
                    entries.extend(ch)
                    success_ips.append((ip, port))
                    break
        if config_bridge.get_scan_config().get("enable_c_scan") and success_ips:
            entries.extend(await smart_c_segment_scan(success_ips, session))
        return entries
    except Exception as e:
        logger.warning(f"[DDGS] 搜索失败: {e}")
        return []

# Tvheadend 扫描（优化版）
async def tvheadend_scan(api_key, query=None, target_size=30, session=None):
    if not api_key:
        logger.warning("[Tvheadend] 未配置 Hunter API Key，跳过")
        return []
    if session is None:
        session = get_session(limit=30, force_close=True)
    if query is None:
        query = 'web.body="Tvheadend" && ip.province=="中国香港"'
    collected_entries = []
    all_ips = []
    page = 1
    page_size = 50
    max_pages = 5
    while len(all_ips) < target_size and page <= max_pages:
        try:
            await asyncio.sleep(API_REQUEST_DELAY * 0.5)
            qb = base64.urlsafe_b64encode(query.encode()).decode().rstrip('=')
            async with session.get(
                "https://hunter.qianxin.com/openApi/search",
                params={
                    "api-key": api_key,
                    "search": qb,
                    "page": page,
                    "page_size": page_size,
                    "is_web": 1
                },
                timeout=aiohttp.ClientTimeout(total=15)
            ) as r:
                if r.status == 200:
                    j = await r.json()
                    if j.get("code") in (200, 0):
                        data = j.get("data") or {}
                        items = data.get("arr") or []
                        if not items:
                            break
                        logger.info(f"[Tvheadend] 第{page}页，{len(items)} 个IP")
                        for item in items:
                            ip = item.get("ip")
                            port = item.get("port", 9981)
                            if ip:
                                all_ips.append((ip, port))
                        if len(items) < page_size:
                            break
                        page += 1
                    else:
                        logger.warning(f"[Tvheadend] API 错误: {j.get('message')}")
                        break
                elif r.status == 403:
                    raise KeyDepletedError("[Tvheadend] Hunter API Key 无效或积分耗尽")
                else:
                    logger.warning(f"[Tvheadend] HTTP {r.status}")
                    break
        except KeyDepletedError:
            raise
        except asyncio.TimeoutError:
            logger.warning("[Tvheadend] 请求超时")
            break
        except Exception as e:
            logger.warning(f"[Tvheadend] 扫描失败: {e}")
            break
    if not all_ips:
        return []
    logger.info(f"[Tvheadend] 共发现 {len(all_ips)} 个IP，开始并发提取（超时3秒，并发20）")
    sem = asyncio.Semaphore(20)
    async def fetch_one(ip, port):
        async with sem:
            try:
                pre_url = f"http://{ip}:{port}/playlist?profile=pass"
                try:
                    async with session.head(pre_url, timeout=aiohttp.ClientTimeout(total=2)) as head_resp:
                        if head_resp.status != 200:
                            return []
                except Exception:
                    return []
                chs = await asyncio.wait_for(extract_tvheadend_channels(ip, port, session), timeout=5)
                return chs
            except asyncio.TimeoutError:
                logger.debug(f"[Tvheadend] {ip}:{port} 超时")
                return []
            except Exception as e:
                logger.debug(f"[Tvheadend] {ip}:{port} 失败: {e}")
                return []
    tasks = [fetch_one(ip, port) for ip, port in all_ips[:target_size]]
    results = await asyncio.gather(*tasks)
    for chs in results:
        if _is_stop_requested():
            logger.info("[Tvheadend] 检测到中止请求，停止扫描")
            break
        collected_entries.extend(chs)
    logger.info(f"[Tvheadend] 共提取 {len(collected_entries)} 个频道")
    return collected_entries

async def extract_tvheadend_channels(ip, port, session):
    base_url = f"http://{ip}:{port}"
    playlist_url = f"{base_url}/playlist?profile=pass"
    try:
        async with session.get(playlist_url, timeout=aiohttp.ClientTimeout(total=3)) as resp:
            if resp.status != 200:
                return []
            text = await resp.text()
            lines = text.splitlines()
            channels = []
            current_name = None
            for line in lines:
                line = line.strip()
                if line.startswith('#EXTINF:'):
                    parts = line.split(',', 1)
                    if len(parts) == 2:
                        current_name = parts[1].strip()
                elif line and not line.startswith('#') and current_name:
                    stream_url = line
                    if not stream_url.startswith('http'):
                        stream_url = urljoin(base_url + '/', stream_url)
                    std_name, cat = resolve_tvheadend_channel(current_name)
                    ch = {
                        'name': std_name,
                        'url': stream_url,
                        'category': cat,
                        'province': '香港',
                        'city': '',
                        'ip_province': '香港',
                        'name_province': None,
                        'source_ip': ip
                    }
                    channels.append(ch)
                    current_name = None
            if channels:
                logger.debug(f"[Tvheadend] 从 {ip}:{port} 提取到 {len(channels)} 个频道")
            return channels
    except asyncio.TimeoutError:
        logger.debug(f"[Tvheadend] 提取 {ip}:{port} 超时")
        return []
    except Exception as e:
        logger.debug(f"[Tvheadend] 提取 {ip}:{port} 失败: {e}")
        return []

def resolve_tvheadend_channel(name):
    from .channel_utils import resolve_name
    std_name, _ = resolve_name(name)
    is_cctv = std_name.startswith('CCTV') or std_name in (
        'CCTV-1','CCTV-2','CCTV-3','CCTV-4','CCTV-5','CCTV-5+','CCTV-6','CCTV-7',
        'CCTV-8','CCTV-9','CCTV-10','CCTV-11','CCTV-12','CCTV-13','CCTV-14',
        'CCTV-15','CCTV-16','CCTV-17'
    )
    if is_cctv:
        cat = '央视频道'
    else:
        cat = '港澳台频道'
    return std_name, cat

# IPTV互动电视系统扫描（修复版）
async def iptv_interactive_scan(api_key, query=None, target_size=30, session=None):
    if not api_key:
        logger.warning("[IPTV互动] 未配置 Hunter API Key，跳过")
        return []
    if session is None:
        session = get_session(limit=30, force_close=True)
    if query is None:
        query = 'title:"首页 - IPTV互动电视系统"'

    collected_entries = []
    all_ips = []
    page = 1
    page_size = 50
    max_pages = 5
    while len(all_ips) < target_size and page <= max_pages:
        try:
            await asyncio.sleep(API_REQUEST_DELAY * 0.5)
            qb = base64.urlsafe_b64encode(query.encode()).decode().rstrip('=')
            async with session.get(
                "https://hunter.qianxin.com/openApi/search",
                params={
                    "api-key": api_key,
                    "search": qb,
                    "page": page,
                    "page_size": page_size,
                    "is_web": 1
                },
                timeout=aiohttp.ClientTimeout(total=15)
            ) as r:
                if r.status == 200:
                    j = await r.json()
                    if j.get("code") in (200, 0):
                        data = j.get("data") or {}
                        items = data.get("arr") or []
                        if not items:
                            break
                        logger.info(f"[IPTV互动] 第{page}页，{len(items)} 个IP")
                        for item in items:
                            ip = item.get("ip")
                            port = item.get("port", 8080)
                            if ip:
                                all_ips.append((ip, port))
                        if len(items) < page_size:
                            break
                        page += 1
                    else:
                        logger.warning(f"[IPTV互动] API 错误: {j.get('message')}")
                        break
                elif r.status == 403:
                    raise KeyDepletedError("[IPTV互动] Hunter API Key 无效或积分耗尽")
                else:
                    logger.warning(f"[IPTV互动] HTTP {r.status}")
                    break
        except KeyDepletedError:
            raise
        except asyncio.TimeoutError:
            logger.warning("[IPTV互动] 请求超时")
            break
        except Exception as e:
            logger.warning(f"[IPTV互动] 扫描失败: {e}")
            break

    if not all_ips:
        return []

    logger.info(f"[IPTV互动] 共发现 {len(all_ips)} 个IP，开始并发提取（超时8秒，并发15）")
    sem = asyncio.Semaphore(15)
    async def fetch_one(ip, port):
        async with sem:
            try:
                chs = await asyncio.wait_for(extract_iptv_interactive_channels(ip, port, session), timeout=8)
                return chs
            except asyncio.TimeoutError:
                logger.debug(f"[IPTV互动] {ip}:{port} 超时")
                return []
            except Exception as e:
                logger.debug(f"[IPTV互动] {ip}:{port} 失败: {e}")
                return []
    tasks = [fetch_one(ip, port) for ip, port in all_ips[:target_size]]
    results = await asyncio.gather(*tasks)
    for chs in results:
        if _is_stop_requested():
            logger.info("[IPTV互动] 检测到中止请求，停止扫描")
            break
        collected_entries.extend(chs)
    logger.info(f"[IPTV互动] 共提取 {len(collected_entries)} 个频道")
    return collected_entries

async def extract_iptv_interactive_channels(ip, port, session):
    base_url = f"http://{ip}:{port}"
    
    # 快速预检
    try:
        async with session.get(base_url, timeout=aiohttp.ClientTimeout(total=3)) as resp:
            if resp.status != 200:
                return []
            text = await resp.text()
            if "IPTV互动电视系统" not in text and "互动电视" not in text:
                return []
    except Exception:
        return []

    channels = []

    # 1. 常见 JSON 接口
    json_endpoints = [
        "/api/channels",
        "/channels",
        "/iptv/live/1000.json",
        "/live/channels.json",
        "/api/live/channels"
    ]
    for endpoint in json_endpoints:
        try:
            url = urljoin(base_url, endpoint)
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if isinstance(data, list):
                        channel_list = data
                    elif isinstance(data, dict):
                        channel_list = data.get("data") or data.get("channels") or []
                    else:
                        continue
                    if channel_list:
                        for ch in channel_list:
                            name = ch.get("name") or ch.get("title") or ch.get("channel_name")
                            ch_id = ch.get("id") or ch.get("channel_id")
                            if not name or not ch_id:
                                continue
                            stream_url = f"{base_url}/live/{ch_id}/index.m3u8"
                            std_name, cat = resolve_iptv_interactive_channel(name)
                            channels.append({
                                'name': std_name,
                                'url': stream_url,
                                'category': cat,
                                'province': '未知',
                                'city': '',
                                'ip_province': '',
                                'name_province': None,
                                'source_ip': ip
                            })
                        if channels:
                            logger.debug(f"[IPTV互动] {ip}:{port} 从 JSON 接口提取到 {len(channels)} 个频道")
                            return channels
        except Exception:
            continue

    # 2. 枚举 /live/ 目录
    try:
        list_url = urljoin(base_url, "/live/")
        async with session.get(list_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status == 200:
                text = await resp.text()
                ids = set(re.findall(r'href="(\d+)/"', text))
                if ids:
                    logger.debug(f"[IPTV互动] {ip}:{port} 从目录发现 {len(ids)} 个节目ID")
                    for ch_id in list(ids)[:50]:
                        stream_url = f"{base_url}/live/{ch_id}/index.m3u8"
                        try:
                            async with session.head(stream_url, timeout=aiohttp.ClientTimeout(total=1.5)) as head_resp:
                                if head_resp.status != 200:
                                    continue
                        except Exception:
                            continue
                        name = f"Channel {ch_id}"
                        std_name, cat = resolve_iptv_interactive_channel(name)
                        channels.append({
                            'name': std_name,
                            'url': stream_url,
                            'category': cat,
                            'province': '未知',
                            'city': '',
                            'ip_province': '',
                            'name_province': None,
                            'source_ip': ip
                        })
                    if channels:
                        logger.debug(f"[IPTV互动] {ip}:{port} 从目录枚举提取到 {len(channels)} 个频道")
                        return channels
    except Exception:
        pass

    # 3. 兜底枚举 1-60
    logger.debug(f"[IPTV互动] {ip}:{port} 尝试兜底枚举 1-60")
    consecutive_failures = 0
    for ch_id in range(1, 61):
        stream_url = f"{base_url}/live/{ch_id}/index.m3u8"
        try:
            async with session.head(stream_url, timeout=aiohttp.ClientTimeout(total=1.5)) as resp:
                if resp.status == 200:
                    consecutive_failures = 0
                    name = f"Channel {ch_id}"
                    std_name, cat = resolve_iptv_interactive_channel(name)
                    channels.append({
                        'name': std_name,
                        'url': stream_url,
                        'category': cat,
                        'province': '未知',
                        'city': '',
                        'ip_province': '',
                        'name_province': None,
                        'source_ip': ip
                    })
                else:
                    consecutive_failures += 1
                    if consecutive_failures > 10:
                        break
        except Exception:
            consecutive_failures += 1
            if consecutive_failures > 10:
                break
    if channels:
        logger.debug(f"[IPTV互动] {ip}:{port} 从兜底枚举提取到 {len(channels)} 个频道")
    return channels

def resolve_iptv_interactive_channel(name):
    from .channel_utils import resolve_name
    std_name, _ = resolve_name(name)
    is_cctv = std_name.startswith('CCTV') or std_name in (
        'CCTV-1','CCTV-2','CCTV-3','CCTV-4','CCTV-5','CCTV-5+','CCTV-6','CCTV-7',
        'CCTV-8','CCTV-9','CCTV-10','CCTV-11','CCTV-12','CCTV-13','CCTV-14',
        'CCTV-15','CCTV-16','CCTV-17'
    ) or '央视' in std_name
    if is_cctv:
        cat = '央视频道'
    else:
        cat = '港澳台频道'
    return std_name, cat

# ---------- 辅助函数 ----------
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


def remove_duplicate_national_channels(channels):
    nat_names = {c['name'] for c in channels if c.get('category') in ('央视频道','央视付费频道','卫视频道')}
    return [c for c in channels if c.get('category') in ('央视频道','央视付费频道','卫视频道') or c['name'] not in nat_names]

def clean_url(u):
    if not isinstance(u, str): return ""
    u = u.strip()
    if u.startswith(('http://', 'https://')):
        if is_valid_stream_url(u): return u
    if u.startswith('//'): return f"http:{u}"
    return ""

def is_valid_channel_name(name):
    if not isinstance(name, str) or not name.strip(): return False
    s = name.strip()
    if len(s) > 60: return False
    if s.startswith(('{','[','<')): return False
    if re.search(r'^(data|javascript|vbscript):', s, re.I): return False
    lowered = s.lower()
    if any(kw in lowered for kw in ['data:text/plain', 'base64,', '"status":', 'null', 'undefined', 'session']): return False
    if any(k in lowered for k in ['api_request','metrics','prometheus','method=','status=']): return False
    if '::' in s or re.search(r'\.[A-Z]', s): return False
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
    if re.search(r'\d{2}:\d{2}:\d{2}', s): return False
    if re.search(r'up \d+ day', lowered): return False
    if re.search(r'mapping\(', lowered): return False
    return True

def deduplicate(sources):
    seen, uniq = set(), []
    for s in sources:
        if s['url'] not in seen: seen.add(s['url']); uniq.append(s)
    return uniq

# ---------- Key 轮换辅助 ----------
class KeyDepletedError(Exception):
    """当前 key 积分耗尽。"""
    pass


async def _run_with_key_rotation(platform, scan_func, *args, session=None, **kwargs):
    """
    用 KeyManager 轮换 key 执行扫描函数。
    scan_func 的第一个参数必须是 api_key。
    按积分余额降序使用 key，跳过已耗尽的 key，403 时自动切换下一个 key 重试。
    """
    from .key_manager import KeyManager, _credit_is_usable, _credit_rank
    km = KeyManager.instance()
    all_keys = km.get_all_keys(platform)
    if not all_keys:
        _stats_set(kwargs.get('stats'), 'skipped_reason', '未配置 API Key')
        return []

    credits = km.get_credits_info(platform)
    sorted_keys = sorted(all_keys, key=lambda k: _credit_rank(credits.get(k)), reverse=True)
    usable = [k for k in sorted_keys if _credit_is_usable(credits.get(k))]

    if not usable:
        logger.warning(f"[{platform}] 所有 key 积分耗尽，跳过扫描")
        _stats_set(kwargs.get('stats'), 'skipped_reason', '所有 API Key 已耗尽')
        return []

    skipped = len(all_keys) - len(usable)
    if skipped:
        logger.info(f"[{platform}] 跳过 {skipped} 个已耗尽的 key，"
                    f"剩余 {len(usable)} 个可用")

    last_error = None
    for key in usable:
        try:
            result = await scan_func(key, *args, session=session, **kwargs)
            return result
        except KeyDepletedError:
            km.mark_depleted(platform, key)
            continue
        except Exception as e:
            last_error = e
            break

    if last_error:
        logger.warning(f"[{platform}] 扫描异常: {last_error}")
        _stats_set(kwargs.get('stats'), 'skipped_reason', str(last_error))
    return []


# ---------- 主收集函数（串行化平台，JSMpeg 全国扫描一次） ----------
async def collect_all(size=None, log_fn=None, platforms_override=None, provinces_override=None):
    """采集所有平台的 IPTV 频道。
    返回 (clean_channels, actual_platforms) 元组。
    log_fn: 可选的日志回调函数，用于将进度写入前端扫描日志。"""
    def _log(msg):
        logger.info(msg)
        if log_fn:
            log_fn(msg)
    from .key_manager import KeyManager
    km = KeyManager.instance()
    scan_cfg = config_bridge.get_scan_config()

    quake_key = km.get_key('quake')
    hunter_key = km.get_key('hunter')
    ddm_key = km.get_key('daydaymap')
    fofa_key = km.get_key('fofa')
    ddgs_enabled = scan_cfg.get("ddgs_enabled", False)

    enabled_platforms = platforms_override if platforms_override is not None else scan_cfg.get("enabled_platforms", [])
    if isinstance(enabled_platforms, str):
        enabled_platforms = [enabled_platforms]
    enabled_platforms = [p for p in (enabled_platforms or []) if isinstance(p, str) and p]
    explicit_platforms = bool(enabled_platforms)
    if not enabled_platforms:
        available_platforms = []
        if km.get_all_keys('quake'): available_platforms.append("quake")
        if km.get_all_keys('hunter'): available_platforms.append("hunter")
        if km.get_all_keys('daydaymap'): available_platforms.append("daydaymap")
        if km.get_all_keys('fofa') and scan_cfg.get("fofa_email"): available_platforms.append("fofa")
        if scan_cfg.get("cost_saver_mode", True):
            preferred_order = ("quake", "fofa", "hunter", "daydaymap")
            enabled_platforms = [
                p for p in preferred_order
                if p in available_platforms
            ][:1]
        else:
            enabled_platforms = available_platforms

    selected_provs = provinces_override if provinces_override is not None else scan_cfg.get("selected_provinces", [])
    if isinstance(selected_provs, str):
        selected_provs = [selected_provs]
    selected_provs = [p for p in (selected_provs or []) if isinstance(p, str)]
    if not selected_provs:
        selected_provs = [scan_cfg.get("province", "") or ""]
    operator = scan_cfg.get("operator", "")

    def _target_for(platform):
        value = size if size is not None else scan_cfg.get(f"{platform}_size", scan_cfg.get("quake_size", 200))
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return 200

    def _quality_target_for(platform, profile_count=None):
        budget = scan_cfg.get("quality_query_profile_size", 120)
        try:
            budget = max(10, int(budget))
        except (TypeError, ValueError):
            budget = 120
        split_count = max(1, (profile_count or len(QUALITY_QUERY_PROFILES)) * len(selected_provs))
        per_profile = max(1, budget // split_count)
        return min(_target_for(platform), per_profile)

    def _with_filters(query, platform, prov=None):
        if not operator and not prov:
            return query
        connector = "AND" if platform == "quake" else "&&"
        filtered = f"({query})"
        if operator:
            filtered += f' {connector} isp="{operator}"'
        if prov:
            if platform == "fofa":
                filtered += f' {connector} region="{prov}"'
            elif platform == "daydaymap":
                filtered += f' {connector} province=="{prov}"'
            else:
                filtered += f' {connector} province="{prov}"'
        return filtered

    def _profile_label(platform_name, profile_label, prov):
        if prov:
            return f"{platform_name}/{profile_label}/{prov}"
        if len(selected_provs) > 1:
            return f"{platform_name}/{profile_label}/全国"
        return f"{platform_name}/{profile_label}"

    def _platform_result_log(name, stats, result_count):
        reason = stats.get('skipped_reason') if isinstance(stats, dict) else None
        if reason:
            return f"[采集] {name} 跳过：{reason}"
        api_items = stats.get('api_items', 0) if isinstance(stats, dict) else 0
        probed = stats.get('probed_hosts', api_items) if isinstance(stats, dict) else api_items
        c_count = stats.get('c_segment_channels', 0) if isinstance(stats, dict) else 0
        suffix = f"，C段补充 {c_count} 条" if c_count else ""
        return f"[采集] {name} 完成：API命中 {api_items} 个，探测 {probed} 个，提取频道 {result_count} 条{suffix}"

    if scan_cfg.get("cost_saver_mode", True) and not explicit_platforms:
        _log(f"[采集] 省积分模式：未手动选择平台，本轮仅使用 {enabled_platforms or '无可用平台'}")
    _log(f"[采集] 启用平台: {enabled_platforms}，省份数: {len(selected_provs)}")

    if not enabled_platforms and not ddgs_enabled and not km.get_all_keys('hunter'):
        _log("[采集] 未启用任何平台且无 Hunter Key，请检查配置")
        return [], [], []

    all_raw = []
    yield_stats = []
    async with get_session(limit=30, force_close=True) as scan_session:
        for prov_idx, prov in enumerate(selected_provs, 1):
            if len(selected_provs) > 1:
                _log(f"[采集] === 省份 ({prov_idx}/{len(selected_provs)}): {prov or '全国'} ===")
            qq = _with_filters(QUAKE_QUERY, "quake", prov)
            hq = _with_filters(HUNTER_QUERY, "hunter", prov)
            ddm_q = _with_filters(DAYDAYMAP_QUERY, "daydaymap", prov)
            fofa_q = _with_filters(FOFA_QUERY, "fofa", prov)

            # 并行执行 API 平台扫描（带 key 轮换），各平台读取各自的扫描数量配置
            api_tasks = []
            if "quake" in enabled_platforms and quake_key:
                stats = {}
                target = _target_for("quake")
                stat_key = _yield_stat_key('platform', 'quake', province=prov)
                api_tasks.append((stat_key, 'Quake 360', 'quake', '', '', prov, _run_with_key_rotation('quake', quake_scan, qq, target, session=scan_session, stats=stats), stats, target))
            elif "quake" in enabled_platforms:
                _log("[采集] Quake 360 已启用但未配置 API Key，跳过")
            if "hunter" in enabled_platforms and hunter_key:
                stats = {}
                target = _target_for("hunter")
                stat_key = _yield_stat_key('platform', 'hunter', province=prov)
                api_tasks.append((stat_key, 'Hunter', 'hunter', '', '', prov, _run_with_key_rotation('hunter', hunter_scan, hq, target, session=scan_session, stats=stats), stats, target))
            elif "hunter" in enabled_platforms:
                _log("[采集] Hunter 已启用但未配置 API Key，跳过")
            if "daydaymap" in enabled_platforms and ddm_key:
                stats = {}
                target = _target_for("daydaymap")
                stat_key = _yield_stat_key('platform', 'daydaymap', province=prov)
                api_tasks.append((stat_key, 'DayDayMap', 'daydaymap', '', '', prov, _run_with_key_rotation('daydaymap', daydaymap_scan, ddm_q, target, session=scan_session, stats=stats), stats, target))
            elif "daydaymap" in enabled_platforms:
                _log("[采集] DayDayMap 已启用但未配置 API Key，跳过")
            if "fofa" in enabled_platforms and fofa_key:
                stats = {}
                target = _target_for("fofa")
                stat_key = _yield_stat_key('platform', 'fofa', province=prov)
                api_tasks.append((stat_key, 'Fofa', 'fofa', '', '', prov, _run_with_key_rotation('fofa', fofa_scan, fofa_q, target, session=scan_session, stats=stats), stats, target))
            elif "fofa" in enabled_platforms:
                _log("[采集] Fofa 已启用但未配置 API Key，跳过")

            if api_tasks:
                labels = ', '.join(f"{n}(目标{target})" for _, n, _, _, _, _, _, _, target in api_tasks)
                _log(f"[采集] ({len(all_raw)}条) 并行扫描: {labels}...")
                async def _run_and_tag(stat_key, name, platform_key, profile, profile_label, stat_prov, coro, stats):
                    try:
                        result = await coro
                        for ch in result:
                            ch['platform'] = name
                            ch['yield_stat_key'] = stat_key
                        _log(_platform_result_log(name, stats, len(result)))
                        yield_stats.append(_build_yield_stat(
                            stat_key, 'platform', platform_key, profile, profile_label, stat_prov, stats, len(result)
                        ))
                        return result
                    except Exception as e:
                        _log(f"[采集] {name} 失败: {e}")
                        yield_stats.append(_build_yield_stat(
                            stat_key, 'platform', platform_key, profile, profile_label, stat_prov, stats, 0
                        ))
                        return []
                results = await asyncio.gather(*[
                    _run_and_tag(stat_key, n, platform_key, profile, profile_label, stat_prov, c, s)
                    for stat_key, n, platform_key, profile, profile_label, stat_prov, c, s, _ in api_tasks
                ])
                for res in results:
                    all_raw.extend(res)
                _log(f"[采集] API 平台完成，本轮获得 {sum(len(r) for r in results)} 条，累计 {len(all_raw)} 条")

        if scan_cfg.get("quality_discovery_enabled", True):
            profile_tasks = []
            enabled_profile_names = set(scan_cfg.get("quality_query_profiles") or [])
            quality_platforms = [
                p for p in (scan_cfg.get("quality_discovery_platforms") or [])
                if p in enabled_platforms
            ]
            if not quality_platforms:
                if scan_cfg.get("cost_saver_mode", True) and not explicit_platforms and "quake" in enabled_platforms:
                    quality_platforms = ["quake"]
                else:
                    quality_platforms = list(enabled_platforms)
            enabled_profiles = [
                profile for profile in QUALITY_QUERY_PROFILES
                if not enabled_profile_names or profile["name"] in enabled_profile_names
            ]
            if quality_platforms and enabled_profiles:
                _log(
                    "[采集] 质量优先查询平台: "
                    f"{quality_platforms}，画像: {', '.join(p['label'] for p in enabled_profiles)}"
                )
            for prov in selected_provs:
                for profile in enabled_profiles:
                    if "quake" in quality_platforms and quake_key:
                        stats = {}
                        target = _quality_target_for("quake", len(enabled_profiles))
                        query = _with_filters(profile["quake"], "quake", prov)
                        stat_key = _yield_stat_key('quality_profile', 'quake', profile["name"], prov)
                        profile_tasks.append((
                            stat_key,
                            _profile_label("Quake 360", profile['label'], prov),
                            "Quake 360",
                            "quake",
                            profile["name"],
                            profile["label"],
                            prov,
                            _run_with_key_rotation('quake', quake_scan, query, target, session=scan_session, stats=stats),
                            stats,
                            target,
                        ))
                    if "hunter" in quality_platforms and hunter_key:
                        stats = {}
                        target = _quality_target_for("hunter", len(enabled_profiles))
                        query = _with_filters(profile["hunter"], "hunter", prov)
                        stat_key = _yield_stat_key('quality_profile', 'hunter', profile["name"], prov)
                        profile_tasks.append((
                            stat_key,
                            _profile_label("Hunter", profile['label'], prov),
                            "Hunter",
                            "hunter",
                            profile["name"],
                            profile["label"],
                            prov,
                            _run_with_key_rotation('hunter', hunter_scan, query, target, session=scan_session, stats=stats),
                            stats,
                            target,
                        ))
                    if "daydaymap" in quality_platforms and ddm_key:
                        stats = {}
                        target = _quality_target_for("daydaymap", len(enabled_profiles))
                        query = _with_filters(profile["daydaymap"], "daydaymap", prov)
                        stat_key = _yield_stat_key('quality_profile', 'daydaymap', profile["name"], prov)
                        profile_tasks.append((
                            stat_key,
                            _profile_label("DayDayMap", profile['label'], prov),
                            "DayDayMap",
                            "daydaymap",
                            profile["name"],
                            profile["label"],
                            prov,
                            _run_with_key_rotation('daydaymap', daydaymap_scan, query, target, session=scan_session, stats=stats),
                            stats,
                            target,
                        ))
                    if "fofa" in quality_platforms and fofa_key:
                        stats = {}
                        target = _quality_target_for("fofa", len(enabled_profiles))
                        query = _with_filters(profile["fofa"], "fofa", prov)
                        stat_key = _yield_stat_key('quality_profile', 'fofa', profile["name"], prov)
                        profile_tasks.append((
                            stat_key,
                            _profile_label("Fofa", profile['label'], prov),
                            "Fofa",
                            "fofa",
                            profile["name"],
                            profile["label"],
                            prov,
                            _run_with_key_rotation('fofa', fofa_scan, query, target, session=scan_session, stats=stats),
                            stats,
                            target,
                        ))

            if profile_tasks:
                labels = ', '.join(f"{name}(目标{target})" for _, name, _, _, _, _, _, _, _, target in profile_tasks)
                _log(f"[采集] ({len(all_raw)}条) 质量优先查询: {labels}...")
                profile_sem = asyncio.Semaphore(4)

                async def _run_quality_profile(stat_key, log_name, platform_name, platform_key, profile_name, profile_label, stat_prov, coro, stats):
                    async with profile_sem:
                        try:
                            result = await coro
                            for ch in result:
                                ch['platform'] = platform_name
                                ch['discovery_profile'] = log_name
                                ch['yield_stat_key'] = stat_key
                            _log(_platform_result_log(log_name, stats, len(result)))
                            yield_stats.append(_build_yield_stat(
                                stat_key, 'quality_profile', platform_key, profile_name, profile_label, stat_prov, stats, len(result)
                            ))
                            return result
                        except Exception as e:
                            _log(f"[采集] {log_name} 失败: {e}")
                            yield_stats.append(_build_yield_stat(
                                stat_key, 'quality_profile', platform_key, profile_name, profile_label, stat_prov, stats, 0
                            ))
                            return []

                results = await asyncio.gather(*[
                    _run_quality_profile(stat_key, log_name, platform_name, platform_key, profile_name, profile_label, stat_prov, coro, stats)
                    for stat_key, log_name, platform_name, platform_key, profile_name, profile_label, stat_prov, coro, stats, _ in profile_tasks
                ])
                for res in results:
                    all_raw.extend(res)
                _log(f"[采集] 质量优先查询完成，本轮获得 {sum(len(r) for r in results)} 条，累计 {len(all_raw)} 条")

        # 独立平台扫描（ZHGX, JSMpeg, Tvheadend, IPTV互动, DDGS）也并行执行
        independent_tasks = []
        indep_size = size or scan_cfg.get("quake_size", 200)

        if enabled_platforms and not scan_cfg.get("cost_saver_mode", True):
            independent_tasks.append(('ZHGX', zhgx_scan(indep_size, session=scan_session)))
        elif enabled_platforms:
            _log("[采集] 省积分模式：跳过独立 ZHGX 扫描")

        # JSMpeg 全国扫描（只执行一次，不限省份）
        if scan_cfg.get("cost_saver_mode", True) and 'jsmpeg' not in (scan_cfg.get("quality_query_profiles") or []):
            _log("[采集] 省积分模式：跳过独立 JSMpeg 扫描")
        else:
            independent_tasks.append(('JSMpeg', jsmpeg_streamer_scan(province=None, operator=operator if operator else None, size=indep_size, session=scan_session)))

        if hunter_key and "hunter" in enabled_platforms:
            independent_tasks.append(('Tvheadend', _run_with_key_rotation('hunter', tvheadend_scan, None, 30, session=scan_session)))
            independent_tasks.append(('IPTV互动', _run_with_key_rotation('hunter', iptv_interactive_scan, None, 30, session=scan_session)))

        if ddgs_enabled:
            independent_tasks.append(('DDGS', ddgs_scan(None, indep_size, session=scan_session)))

        if independent_tasks:
            _log(f"[采集] ({len(all_raw)}条) 并行扫描独立平台: {', '.join(n for n, _ in independent_tasks)}...")
            async def _run_independent(name, coro):
                try:
                    result = await asyncio.wait_for(coro, timeout=PLATFORM_TIMEOUT)
                    for ch in result:
                        if name == 'JSMpeg':
                            ch['platform'] = ch.pop('scan_source', 'Quake 360')
                        else:
                            ch['platform'] = name
                    _log(f"[采集] {name} 完成：提取频道 {len(result)} 条")
                    return result
                except asyncio.TimeoutError:
                    _log(f"[采集] {name} 超时，放弃")
                    return []
                except Exception as e:
                    _log(f"[采集] {name} 失败: {e}")
                    return []
            results = await asyncio.gather(*[_run_independent(n, c) for n, c in independent_tasks])
            for res in results:
                all_raw.extend(res)
            _log(f"[采集] 独立平台完成，本轮获得 {sum(len(r) for r in results)} 条，累计 {len(all_raw)} 条")

        # 域名/IP 扫描
        _log(f"[采集] ({len(all_raw)}条) 开始域名/IP扫描...")
        try:
            from .domain_ip_scanner import domain_ip_scan
            domain_entries = await domain_ip_scan(session=scan_session)
            scan_ports = scan_cfg.get(
                'scan_ports', [8080, 80, 443, 9981, 8888, 8000, 9090, 3000, 5000, 8443])
            for ent in domain_entries:
                ip = ent['ip']
                for port in scan_ports:
                    ch = await extract_channels_from_ip(ip, port, scan_session)
                    if ch:
                        for c in ch:
                            c['platform'] = '域名/IP'
                        all_raw.extend(ch)
                        break
            _log(f"[采集] 域名/IP扫描 完成，累计 {len(all_raw)} 条")
        except Exception as e:
            _log(f"[采集] 域名/IP扫描 失败: {e}")

    clean = []
    invalid_url_count = 0
    invalid_name_count = 0
    blacklisted_count = 0
    for ent in all_raw:
        url = clean_url(ent.get('url', ''))
        name = ent.get('name', '')
        if not url:
            invalid_url_count += 1
            continue
        if not is_valid_channel_name(name):
            invalid_name_count += 1
            continue
        if is_blacklisted(name):
            blacklisted_count += 1
            continue
        ent['url'] = url
        ent['province'] = ent.get('province') or '未知'
        ent['ip_province'] = ent.get('ip_province') or ent.get('province', '未知')
        ent['name_province'] = ent.get('name_province')
        ent['source_ip'] = ent.get('source_ip', '')
        clean.append(ent)
    # 检测实际启用的平台（用于记录 platforms_used）
    actual_platforms = []
    if ddgs_enabled:
        actual_platforms.append('ddgs')
    if enabled_platforms:
        actual_platforms.extend(enabled_platforms)

    dropped = invalid_url_count + invalid_name_count + blacklisted_count
    if dropped:
        _log(
            f"[采集] 清洗丢弃 {dropped} 条：无效URL {invalid_url_count}，"
            f"无效频道名 {invalid_name_count}，黑名单 {blacklisted_count}"
        )
    clean_counts = {}
    for ent in clean:
        stat_key = ent.get('yield_stat_key')
        if stat_key:
            clean_counts[stat_key] = clean_counts.get(stat_key, 0) + 1
    for row in yield_stats:
        stat_key = row.get('stat_key')
        row['cleaned_channels'] = clean_counts.get(stat_key, 0)
    _log(f"[采集] 全部平台扫描完成，原始 {len(all_raw)} 条，清洗后 {len(clean)} 条")
    return clean, actual_platforms, yield_stats

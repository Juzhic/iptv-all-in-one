"""Bounded udpxy discovery; generated HTTP streams use the normal quality pipeline."""
import asyncio
import ipaddress
import itertools
import re
from datetime import date
from urllib.parse import urlsplit

import aiohttp

from ..multicast_templates import (
    normalize_proxy_url, parse_manual_proxies, selected_templates, validate_config,
)
from ..safe_http import read_response_limited, safe_fetch
from .shared import (
    KeyDepletedError, _build_yield_stat, _is_stop_requested, _make_channel_entry,
    _stats_add, _yield_stat_key, safe_decode_json,
)

MAX_RUN_SECONDS = 120
MAX_SEARCH_SECONDS = 60


async def search_quake_proxies(api_key, query, target_size, *, session, stats=None, cursor=None):
    """Return public endpoints, keeping partial results when a key is depleted."""
    result = []
    cursor = {} if cursor is None else cursor
    for start in range(cursor.get('start', 0), target_size, 50):
        if _is_stop_requested():
            break
        size = min(50, target_size - start)
        await asyncio.sleep(0.75)
        if _is_stop_requested():
            break
        async with session.post(
            'https://quake.360.net/api/v3/search/quake_service',
            headers={'X-QuakeToken': api_key, 'Content-Type': 'application/json'},
            json={'query': query, 'start': start, 'size': size, 'latest': True},
            timeout=aiohttp.ClientTimeout(total=15), allow_redirects=False,
        ) as response:
            body = safe_decode_json(await read_response_limited(response, 1024 * 1024))
            if not isinstance(body, dict):
                raise ValueError('Quake 组播查询返回无效响应')
            if response.status != 200 or str(body.get('code')) != '0':
                # Permission, authentication and rate-limit failures do not mean
                # that a key has no credits. Never echo upstream errors or keys.
                message = str(body.get('message', body.get('msg', ''))).lower()
                if (response.status in (200, 400) and
                        re.search(r'(积分|余额|额度).*(不足|耗尽)|insufficient.*(credit|balance)|quota.*exceed', message)):
                    error = KeyDepletedError('Quake 组播查询额度不足')
                    error.partial_entries = result
                    raise error
                if stats is not None:
                    stats['skipped_reason'] = f'Quake 组播查询失败（HTTP {response.status}）'
                break
            items = body.get('data')
            if not isinstance(items, list):
                raise ValueError('Quake 组播查询缺少结果列表')
            _stats_add(stats, 'api_items', min(len(items), size))
            cursor['start'] = start + min(len(items), size)
            for item in items[:size]:
                if not isinstance(item, dict):
                    continue
                try:
                    address = ipaddress.ip_address(item.get('ip'))
                    host = f'[{address}]' if address.version == 6 else str(address)
                    port = int(item.get('port', 80))
                    url = normalize_proxy_url(f'http://{host}:{port}')
                except (ValueError, TypeError):
                    continue
                location = item.get('location') or {}
                result.append({'url': url, 'city': str(location.get('city_cn', ''))[:64]
                               if isinstance(location, dict) else '',
                               'platform': 'Quake 360', 'origin': 'quake'})
            if len(items) < size:
                break
    return result


def is_transport_stream(data):
    """Require three MPEG-TS sync bytes, not merely HTTP 200 or a media header."""
    return any(data[offset] == data[offset + 188] == data[offset + 376] == 0x47
               for offset in range(min(188, max(0, len(data) - 376))))


async def _stream_sample(session, url):
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=4),
                               allow_redirects=False) as response:
            if response.status != 200:
                return False
            try:
                sample = await response.content.readexactly(1316)
            except asyncio.IncompleteReadError as error:
                sample = error.partial
            return is_transport_stream(sample)
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return False


async def probe_proxy(proxy, template, session, semaphore):
    async with semaphore:
        if _is_stop_requested():
            return None
        base = normalize_proxy_url(proxy['url'])
        active = None
        try:
            response = await safe_fetch(base + '/status', timeout=3,
                                        max_bytes=128 * 1024, max_redirects=0)
            if response.status == 200:
                html = response.text()
                # Status is optional: deployments can hide it while serving TS.
                plain = re.sub(r'<[^>]*>', ' ', html)
                match = re.search(r'(?:active\s+clients|clients\s+active)\s*:?\s*(\d+)', plain, re.I)
                if match:
                    active = int(match.group(1))
        except (ValueError, LookupError, aiohttp.ClientError, asyncio.TimeoutError):
            pass
        channels = template['channels']
        indexes = dict.fromkeys((0, len(channels) // 2, len(channels) - 1))
        for index in indexes:
            if _is_stop_requested():
                return None
            channel = channels[index]
            url = f"{base}/{channel['protocol']}/{channel['address']}"
            if await _stream_sample(session, url):
                return {**proxy, 'url': base, 'active_clients': active}
    return None


def _proxy_channels(proxy, template, stat_key):
    host = urlsplit(proxy['url']).hostname
    for channel in template['channels']:
        url = f"{proxy['url']}/{channel['protocol']}/{channel['address']}"
        entry = _make_channel_entry(channel['name'], url, proxy['url'],
                                    proxy['province'], proxy.get('city', ''), host)
        if entry:
            entry.update(platform=proxy['platform'], yield_stat_key=stat_key,
                         discovery_profile='UDPXY 组播', operator=proxy['operator'])
            yield entry


async def collect_multicast(cfg, platforms, provinces, *, session, log_fn):
    if not cfg.get('multicast_enabled'):
        return [], []
    from .collector import _run_with_key_rotation

    log = lambda message: log_fn(f'[组播] {message}')
    try:
        validate_config(cfg)
        templates = selected_templates(cfg, provinces)
        manual = parse_manual_proxies(cfg.get('multicast_proxy_urls', ''))
    except ValueError as error:
        log(f'配置无效：{error}')
        return [], []
    if not templates:
        log('当前省份/运营商没有有效组播模板，请添加自定义 TXT/M3U 模板')
        return [], []

    max_proxies = cfg.get('multicast_max_proxies', 20)
    max_channels = cfg.get('multicast_max_channels', 500)
    budget = cfg.get('multicast_search_size', 60)
    stats = {'quake': {'target_size': budget}, 'udpxy': {'target_size': len(manual)}}
    proxies, live, seen = [], [], set()

    def add_proxy(proxy):
        key = proxy['province'], proxy['operator']
        identity = (*key, proxy['url'])
        if key in templates and identity not in seen and len(proxies) < max_proxies:
            seen.add(identity)
            proxies.append(proxy)

    for proxy in manual:
        add_proxy(proxy)
    unmatched = sum((proxy['province'], proxy['operator']) not in templates for proxy in manual)
    if unmatched:
        log(f'{unmatched} 条手动代理不在本轮范围内或没有匹配模板，已跳过')
    log(f'匹配 {len(templates)} 组模板；最多探测 {max_proxies} 个代理，生成 {max_channels} 条候选')
    try:
        async with asyncio.timeout(MAX_RUN_SECONDS):
            if cfg.get('multicast_quake_enabled', True) and 'quake' in platforms:
                # Rotate groups daily so a small global budget does not always
                # exclude the same provinces/operators. Manual proxies go first.
                groups = list(templates)
                offset = date.today().toordinal() % len(groups)
                groups = groups[offset:] + groups[:offset]
                base, extra = divmod(budget, len(groups))
                try:
                    async with asyncio.timeout(MAX_SEARCH_SECONDS):
                        for index, (province, operator) in enumerate(groups):
                            target = base + (index < extra)
                            if _is_stop_requested() or len(proxies) >= max_proxies:
                                break
                            if target <= 0:
                                continue
                            query = (f'udpxy AND country_cn:"中国" AND '
                                     f'province_cn:"{province}" AND isp:"{operator}"')
                            endpoints = await _run_with_key_rotation(
                                'quake', search_quake_proxies, query, target,
                                session=session, stats=stats['quake'], cursor={})
                            for endpoint in endpoints:
                                add_proxy({**endpoint, 'province': province, 'operator': operator})
                            log(f'{province}/{operator}：搜索得到 {len(endpoints)} 个代理')
                            if stats['quake'].get('skipped_reason'):
                                log(stats['quake']['skipped_reason'])
                                break
                except asyncio.TimeoutError:
                    log('搜索达到 60 秒上限，继续验证已收集代理')
            elif cfg.get('multicast_quake_enabled', True):
                log('本轮未选择 Quake 平台，仅处理手动代理')

            semaphore = asyncio.Semaphore(5)

            async def check(proxy):
                if _is_stop_requested():
                    return
                _stats_add(stats[proxy['origin']], 'probed_hosts', 1)
                try:
                    result = await probe_proxy(proxy, templates[(proxy['province'], proxy['operator'])],
                                               session, semaphore)
                    if result:
                        live.append(result)
                except (ValueError, aiohttp.ClientError, asyncio.TimeoutError):
                    pass

            await asyncio.gather(*(check(proxy) for proxy in proxies))
    except asyncio.TimeoutError:
        log('达到 120 秒时间上限，保留已验证代理')

    stat_keys = {origin: _yield_stat_key('multicast', origin, 'udpxy') for origin in stats}
    # Prefer lower reported load, but keep each proxy represented within the
    # channel budget. One successful sample never assigns quality to other URLs.
    live.sort(key=lambda proxy: proxy['active_clients'] if proxy['active_clients'] is not None else float('inf'))
    candidates, urls = [], set()
    iterators = [_proxy_channels(proxy, templates[(proxy['province'], proxy['operator'])],
                                 stat_keys[proxy['origin']]) for proxy in live]
    for group in itertools.zip_longest(*iterators):
        if _is_stop_requested() or len(candidates) >= max_channels:
            break
        for channel in group:
            if channel and channel['url'] not in urls:
                urls.add(channel['url'])
                candidates.append(channel)
                if len(candidates) >= max_channels:
                    break
    rows = []
    for origin, values in stats.items():
        count = sum(channel['yield_stat_key'] == stat_keys[origin] for channel in candidates)
        values['extracted_channels'] = count
        if values.get('api_items') or values.get('probed_hosts') or values.get('skipped_reason'):
            rows.append(_build_yield_stat(stat_keys[origin], 'multicast', origin, 'udpxy',
                                         'UDPXY 组播', '', values, count))
    log(f'完成：{len(proxies)} 个代理候选，{len(live)} 个通过 TS 抽检，'
        f'{len(candidates)} 条频道进入逐条快速检测和深测')
    return candidates, rows

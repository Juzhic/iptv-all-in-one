"""UDPXY extraction shared by platform collection and manual IP scans.

Search APIs stay in their existing platform adapters. This module only matches
endpoints to multicast templates, verifies a sample and expands candidates.
"""
import asyncio
import ipaddress
import itertools
import re
from contextlib import contextmanager
from contextvars import ContextVar
from urllib.parse import urlsplit

import aiohttp

from ..multicast_templates import (
    normalize_proxy_url, normalize_province, normalize_operator,
    parse_manual_proxies, selected_templates, multicast_address,
)
from ..safe_http import safe_fetch
from .shared import _is_stop_requested, _make_channel_entry

MAX_RUN_SECONDS = 120
_runtime = ContextVar('udpxy_runtime', default=None)
_source = ContextVar('udpxy_source', default={})


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


async def probe_proxy(proxy, template, session, semaphore, stop_requested=None):
    stopped = stop_requested or _is_stop_requested
    async with semaphore:
        if stopped():
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
            if stopped():
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
            if proxy.get('c_segment_expanded'):
                entry['c_segment_expanded'] = True
            yield entry


def channel_proxy(url):
    """Recover a public HTTP IPv4 proxy prefix from a multicast playback URL."""
    if not isinstance(url, str):
        return None
    try:
        parsed = urlsplit(url)
        destination = multicast_address(url)
        if not destination or parsed.query or parsed.fragment or parsed.scheme != 'http':
            return None
        prefix, _protocol, _address = parsed.path.rsplit('/', 2)
        base = normalize_proxy_url(f'{parsed.scheme}://{parsed.netloc}{prefix}')
        if ipaddress.ip_address(parsed.hostname).version != 4:
            return None
        return base, destination
    except (TypeError, ValueError):
        return None


def seed_template(seed, cfg):
    """Prefer an unambiguous template; old DB rows can lack ISP/IP-location data."""
    parsed = channel_proxy(seed.get('url', ''))
    if not parsed:
        return None
    base, destination = parsed
    province = normalize_province(seed.get('ip_province')) or normalize_province(seed.get('province'))
    operator = normalize_operator(seed.get('operator'))
    templates = selected_templates(cfg, [province] if province else [])
    matches = [item for (_, isp), item in templates.items()
               if (not operator or isp == operator)
               and any((ch['protocol'], ch['address']) == destination for ch in item['channels'])]
    if len(matches) == 1:
        template = matches[0]
        province, operator = template['province'], template['operator']
    else:
        # A verified destination is still useful when a historical template
        # changed or multiple operators reused the same multicast address.
        template = {'province': province, 'operator': operator, 'source': 'verified',
                    'channels': [{'name': seed.get('name', ''), 'protocol': destination[0],
                                  'address': destination[1]}]}
    proxy = dict(url=base, province=province, operator=operator, city=seed.get('city', ''),
                 platform=seed.get('platform') or '复检C段拓展', stat_key='', c_segment_expanded=True)
    return proxy, template


def neighbor_proxy(proxy, ip, port):
    """Change only the IPv4 host, keeping the port and proxy mount prefix."""
    parsed = urlsplit(normalize_proxy_url(proxy['url']))
    original, neighbor = ipaddress.ip_address(parsed.hostname), ipaddress.ip_address(ip)
    if (parsed.scheme != 'http' or original.version != 4 or neighbor.version != 4
            or neighbor == original or (parsed.port or 80) != port
            or neighbor not in ipaddress.ip_network(f'{original}/24', strict=False)):
        raise ValueError('UDPXY 拓展仅限同 C 段、同端口的其他公网 IPv4')
    url = normalize_proxy_url(f'http://{neighbor}:{port}{parsed.path}')
    return {**proxy, 'url': url, 'c_segment_expanded': True}


async def probe_neighbor(proxy, template, ip, port, session, semaphore, max_channels):
    candidate = neighbor_proxy(proxy, ip, port)
    result = await probe_proxy(candidate, template, session, semaphore, lambda: False)
    if not result:
        return []
    return list(itertools.islice(_proxy_channels(result, template, proxy['stat_key']), max_channels))


@contextmanager
def discovery_source(platform='', stat_key='', province='', *, udpxy_only=False):
    """Carry query provenance into the common IP extractor, including C scans."""
    token = _source.set(dict(platform=platform, stat_key=stat_key,
                             province=province, udpxy_only=udpxy_only))
    try:
        yield
    finally:
        _source.reset(token)


@contextmanager
def multicast_run(cfg, provinces, log_fn=None, stop_requested=None):
    discovery = MulticastDiscovery(cfg, provinces, log_fn, stop_requested)
    token = _runtime.set(discovery)
    try:
        yield discovery
    finally:
        _runtime.reset(token)


def current_discovery():
    return _runtime.get()


def is_udpxy_query():
    return bool(_source.get().get('udpxy_only'))


def current_source_key():
    return _source.get().get('stat_key')


class MulticastDiscovery:
    """One bounded queue per scan, shared across platforms, queries and hosts."""

    def __init__(self, cfg, provinces, log_fn=None, stop_requested=None):
        self.cfg = cfg
        self.enabled = cfg.get('multicast_enabled', False)
        self.log = log_fn or (lambda message: None)
        try:
            self.templates = selected_templates(cfg, provinces) if self.enabled else {}
        except (TypeError, ValueError):
            self.templates = {}
            self.log('[UDPXY] 模板配置无效，跳过组播识别；请重新保存模板')
        self.max_proxies = cfg.get('multicast_max_proxies', 20)
        self.max_channels = cfg.get('multicast_max_channels', 500)
        self.stopped = stop_requested or _is_stop_requested
        self.proxies = []
        self.seen = set()
        self.checked = {}
        self.unmatched = set()
        self.expansion_stats = {}

    def add(self, url, province='', operator='', city='', source=None):
        if not self.enabled or self.stopped():
            return
        try:
            url = normalize_proxy_url(url)
        except ValueError:
            return
        source = source if source is not None else _source.get()
        province = normalize_province(province) or normalize_province(source.get('province'))
        operator = normalize_operator(operator)
        groups = [key for key in self.templates if (not province or key[0] == province)
                  and (not operator or key[1] == operator)]
        # No geographic information: only use an explicitly narrowed scope.
        if not province and len({key[0] for key in groups}) > 1:
            self.unmatched.add(url)
            return
        if not groups:
            self.unmatched.add(url)
        for group in groups:
            key = (url, *group)
            if key in self.seen or len(self.proxies) >= self.max_proxies:
                continue
            self.seen.add(key)
            self.proxies.append(dict(url=url, province=group[0], operator=group[1],
                                     city=city, platform=source.get('platform') or 'IP 探测',
                                     stat_key=source.get('stat_key', '')))

    async def offer(self, url, province='', operator='', city='', *, direct=False, source=None):
        """Known UDPXY queries need no status page; generic hosts must identify it."""
        if not self.templates or self.stopped() or len(self.proxies) >= self.max_proxies:
            return
        try:
            base = normalize_proxy_url(url)
        except ValueError:
            return
        if direct:
            self.add(base, province, operator, city, source)
            return
        if base in self.checked:
            matched = self.checked[base]
            if matched:
                self.add(matched, province, operator, city, source)
            return bool(matched)
        self.checked[base] = None
        for prefix in ('', '/udpxy'):
            if self.stopped():
                break
            try:
                response = await safe_fetch(base + prefix + '/status', timeout=3,
                                            max_bytes=128 * 1024, max_redirects=0)
                if response.status == 200 and re.search(r'\budpxy\b', response.text(), re.I):
                    self.checked[base] = base + prefix
                    self.add(base + prefix, province, operator, city, source)
                    return True
            except (ValueError, LookupError, aiohttp.ClientError, asyncio.TimeoutError):
                continue

    def add_legacy_proxies(self, cfg):
        """Honor saved 3.5 proxy seeds without retaining a second search pipeline."""
        if not self.enabled:
            return
        try:
            proxies = parse_manual_proxies(cfg.get('multicast_proxy_urls', ''))
        except ValueError:
            self.log('[UDPXY] 旧版已保存代理格式无效，跳过这些代理')
            return
        for proxy in proxies:
            self.add(proxy['url'], proxy['province'], proxy['operator'],
                     source={'platform': 'UDPXY', 'stat_key': 'manual|udpxy|all|all'})

    async def _expand_verified(self, seeds, check):
        # Imported lazily because the common extractor also imports this module.
        from .ip_extract import get_c_segment_budget, _pick_c_segment_ips

        if not self.cfg.get('enable_c_scan') or self.stopped():
            return
        budget = get_c_segment_budget(self.cfg)
        known = {(urlsplit(proxy['url']).hostname, urlsplit(proxy['url']).port or 80)
                 for proxy in self.proxies}
        visited = set()
        for seed in seeds:
            if self.stopped() or len(self.proxies) >= self.max_proxies:
                break
            parsed = urlsplit(seed['url'])
            address = ipaddress.ip_address(parsed.hostname)
            if parsed.scheme != 'http' or address.version != 4:
                continue
            segment, port = str(address).rsplit('.', 1)[0], parsed.port or 80
            if (segment, port) in visited:
                continue
            visited.add((segment, port))
            ips = [ip for ip in _pick_c_segment_ips(str(address), 254)
                   if (ip, port) not in known]
            ips.sort(key=lambda ip: abs(int(ip.rsplit('.', 1)[1]) - int(address.packed[-1])))
            ips = ips[:min(self.cfg.get('c_scan_limit', 50), self.max_proxies - len(self.proxies))]
            if not ips:
                continue
            endpoints, summary = await budget.reserve(seed['stat_key'] or 'udpxy', [(segment, port, ips)])
            stats = self.expansion_stats.setdefault(seed['stat_key'], {})
            for field, value in summary.items():
                key = f'c_segment_{field}'
                stats[key] = stats.get(key, 0) + value
            neighbors = []
            for ip, neighbor_port in endpoints:
                try:
                    candidate = neighbor_proxy(seed, ip, neighbor_port)
                except ValueError:
                    continue
                self.proxies.append(candidate)
                self.seen.add((candidate['url'], candidate['province'], candidate['operator']))
                known.add((ip, neighbor_port))
                neighbors.append(candidate)
            if neighbors:
                self.log(f'[UDPXY C段] 从已通过抽检的代理拓展 {segment}.0/24:{port}，探测 {len(neighbors)} 个邻近 IP')
                # The seed list is a snapshot: newly found proxies never recurse.
                await asyncio.gather(*(check(proxy) for proxy in neighbors))

    async def finish(self, session, *, expand_c_segments=False):
        live = []
        semaphore = asyncio.Semaphore(5)

        async def check(proxy):
            if self.stopped():
                return
            try:
                result = await probe_proxy(proxy, self.templates[(proxy['province'], proxy['operator'])],
                                           session, semaphore, self.stopped)
                if result:
                    live.append(result)
            except Exception as error:
                self.log(f'[UDPXY] 单个代理探测失败（{type(error).__name__}），继续其他目标')

        try:
            async with asyncio.timeout(MAX_RUN_SECONDS):
                await asyncio.gather(*(check(proxy) for proxy in self.proxies))
                if expand_c_segments:
                    await self._expand_verified(list(live), check)
        except asyncio.TimeoutError:
            self.log('[UDPXY] 探测达到 120 秒上限，保留已验证结果')
        live.sort(key=lambda proxy: proxy['active_clients']
                  if proxy.get('active_clients') is not None else float('inf'))
        streams = [_proxy_channels(proxy, self.templates[(proxy['province'], proxy['operator'])],
                                   proxy['stat_key']) for proxy in live]
        channels, urls = [], set()
        for group in itertools.zip_longest(*streams):
            if self.stopped() or len(channels) >= self.max_channels:
                break
            for channel in group:
                if channel and channel['url'] not in urls:
                    urls.add(channel['url'])
                    channels.append(channel)
                    if channel.get('c_segment_expanded'):
                        stats = self.expansion_stats.setdefault(channel['yield_stat_key'], {})
                        stats['c_segment_channels'] = stats.get('c_segment_channels', 0) + 1
                    if len(channels) >= self.max_channels:
                        break
        if self.enabled:
            self.log(f'[UDPXY] {len(self.proxies)} 个代理/模板组合，{len(live)} 个通过 TS 抽检，'
                     f'{len(channels)} 条候选；频道质量仍需逐条检测')
            if self.unmatched:
                self.log(f'[UDPXY] {len(self.unmatched)} 个地址未匹配模板或缺少省份，请检查模板范围')
        return channels

"""Streaming playback transport: validate and pin each destination, including redirects."""
import ipaddress
import re
import socket
from urllib.parse import urljoin, urlsplit

import urllib3

from scanner_integration.safe_http import (
    NetworkPolicyError, REDIRECT_STATUSES, validate_http_url, validate_resolved_addresses,
)

MAX_PLAYLIST_BYTES = 1024 * 1024
HLS_TYPES = {'application/vnd.apple.mpegurl', 'application/x-mpegurl', 'audio/mpegurl', 'audio/x-mpegurl'}


def validate_playback_url(url):
    host, port = validate_http_url(url)
    parsed = urlsplit(url)
    if parsed.username is not None or parsed.password is not None or '\\' in url:
        raise NetworkPolicyError('播放代理不支持带账号密码或反斜杠的地址')
    return host, port or (443 if parsed.scheme == 'https' else 80)


def _resolve(host, port):
    try:
        return [str(ipaddress.ip_address(host))]
    except ValueError:
        return [item[4][0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]


class Upstream:
    def __init__(self, response, pool, url):
        self.response, self.pool, self.url = response, pool, url

    def close(self):
        self.response.close()
        self.pool.close()


def open_upstream(url, range_header=None):
    """Never forward browser credentials/cookies or use environment HTTP proxies."""
    for hop in range(4):
        host, port = validate_playback_url(url)
        addresses = validate_resolved_addresses(host, _resolve(host, port))
        parsed = urlsplit(url)
        headers = {'Host': parsed.netloc, 'User-Agent': 'IPTV-Player/1.0', 'Accept-Encoding': 'identity'}
        if range_header:
            headers['Range'] = range_header
        # Connect to the verified IP, while keeping the original Host, SNI and
        # certificate hostname. No second hostname resolution can rebind to LAN.
        if parsed.scheme == 'https':
            pool = urllib3.HTTPSConnectionPool(addresses[0], port, assert_hostname=host, server_hostname=host)
        else:
            pool = urllib3.HTTPConnectionPool(addresses[0], port)
        try:
            path = parsed.path or '/'
            if parsed.query:
                path += '?' + parsed.query
            response = pool.urlopen('GET', path, headers=headers, preload_content=False,
                                    redirect=False, retries=False,
                                    timeout=urllib3.Timeout(connect=5, read=12))
        except Exception:
            pool.close()
            raise
        upstream = Upstream(response, pool, url)
        if response.status not in REDIRECT_STATUSES:
            return upstream
        location = response.headers.get('Location', '')
        upstream.close()
        if not location or hop == 3:
            raise NetworkPolicyError('源站重定向无效或次数过多')
        url = urljoin(url, location)
    raise NetworkPolicyError('源站重定向次数过多')


def rewrite_playlist(text, base_url, make_url):
    """Rewrite segment lines and URI attributes (KEY/MAP/MEDIA/I-FRAME/etc.)."""
    if not text.lstrip('\ufeff\r\n ').startswith('#EXTM3U'):
        raise ValueError('源站返回的内容不是有效 M3U8 播放列表')

    def replace_uri(uri):
        # Inline keys contain no network request. DRM schemes are not proxied.
        if uri.startswith('data:'):
            return uri
        if '{$' in uri:
            raise ValueError('暂不支持包含变量引用的 HLS 地址')
        target = urljoin(base_url, uri)
        validate_playback_url(target)
        return make_url(target)

    lines = []
    for line in text.lstrip('\ufeff').splitlines():
        stripped = line.strip()
        # Steering JSON embeds another family of remote URLs; the primary
        # variants remain usable without this optional CDN steering extension.
        if stripped.startswith('#EXT-X-CONTENT-STEERING:'):
            continue
        if stripped.startswith('#'):
            line = re.sub(r'\bURI="([^"]*)"', lambda m: 'URI="' + replace_uri(m[1]) + '"', line)
        elif stripped:
            line = replace_uri(stripped)
        lines.append(line)
    return '\n'.join(lines) + '\n'

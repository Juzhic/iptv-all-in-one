"""Offline multicast channel templates and strict, bounded configuration parsing."""
import ipaddress
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

PROVINCES = (
    '北京', '天津', '上海', '重庆', '河北', '山西', '辽宁', '吉林', '黑龙江',
    '江苏', '浙江', '安徽', '福建', '江西', '山东', '河南', '湖北', '湖南',
    '广东', '海南', '四川', '贵州', '云南', '陕西', '甘肃', '青海', '台湾',
    '内蒙古', '广西', '西藏', '宁夏', '新疆', '香港', '澳门',
)
OPERATORS = ('电信', '联通', '移动')
MAX_TEMPLATE_CHARS = 128_000
MAX_CUSTOM_TEMPLATES = 32
MAX_TEMPLATE_CHANNELS = 2000
BUILTIN_REVISION = 'ba1f1dea5f878f2ac536790418e81b4f25f3cb75'
_DATA_DIR = Path(__file__).parent / 'data' / 'spider_iptv'


def normalize_province(value):
    value = str(value or '').strip()
    return next((province for province in PROVINCES if value == province or
                 value in (province + '省', province + '市', province + '自治区',
                           province + '壮族自治区', province + '回族自治区',
                           province + '维吾尔自治区', province + '特别行政区')), '')


def normalize_operator(value):
    value = str(value or '').strip()
    aliases = {'CHINANET': '电信', 'CHINA TELECOM': '电信', 'CHINA UNICOM': '联通',
               'CHINA MOBILE': '移动', 'CMCC': '移动'}
    value = aliases.get(value.upper(), value)
    return next((operator for operator in OPERATORS
                 if value in (operator, '中国' + operator)), '')


def multicast_address(value):
    """Extract only the multicast destination; never retain an old proxy host."""
    value = value.strip().split('$', 1)[0]
    match = re.fullmatch(r'(rtp|udp)://@?(\d+(?:\.\d+){3}):(\d+)', value, re.I)
    if not match:
        try:
            parsed = urlsplit(value)
            if parsed.scheme not in ('http', 'https') or not parsed.hostname:
                return None
            match = re.fullmatch(r'.*/(rtp|udp)/(\d+(?:\.\d+){3}):(\d+)', parsed.path, re.I)
        except ValueError:
            return None
    if not match:
        return None
    protocol, host, port = match.groups()
    try:
        address = ipaddress.IPv4Address(host)
        port = int(port)
        if address.is_multicast and 1 <= port <= 65535:
            return protocol.lower(), f'{address}:{port}'
    except ValueError:
        pass
    return None


def parse_playlist(content):
    """Read TXT or extended M3U data, excluding ads, unicast URLs and duplicates."""
    if not isinstance(content, str) or len(content) > MAX_TEMPLATE_CHARS:
        raise ValueError('单个组播模板最多允许 128000 字符')
    channels, seen = [], set()
    pending_name = None
    for line in content.lstrip('\ufeff').splitlines():
        line = line.strip()
        if line.upper().startswith('#EXTINF:'):
            pending_name = line.split(',', 1)[1].strip() if ',' in line else None
            continue
        if not line or line.startswith('#'):
            continue
        if pending_name is not None:
            name, urls = pending_name, line
            pending_name = None
        elif ',' in line:
            name, urls = line.split(',', 1)
            name = name.strip()
        else:
            continue
        if not name or len(name) > 128 or any(ord(char) < 32 for char in name):
            continue
        for url in urls.split('#'):
            destination = multicast_address(url)
            if destination is None or destination in seen:
                continue
            seen.add(destination)
            protocol, address = destination
            channels.append({'name': name, 'protocol': protocol, 'address': address})
            if len(channels) >= MAX_TEMPLATE_CHANNELS:
                return channels
    return channels


@lru_cache(maxsize=1)
def builtin_templates():
    groups = {}
    for path in sorted(_DATA_DIR.glob('*.txt')):
        parts = path.stem.split('-')
        if len(parts) < 3:
            continue
        province, operator = normalize_province(parts[0]), normalize_operator(parts[1])
        if not province or not operator:
            continue
        channels = parse_playlist(path.read_text(encoding='utf-8-sig'))
        if channels:
            groups.setdefault((province, operator), []).extend(channels)
    result = []
    for (province, operator), channels in groups.items():
        unique = {}
        for channel in channels:
            unique.setdefault((channel['protocol'], channel['address']), channel)
        result.append({'province': province, 'operator': operator,
                       'channels': list(unique.values()), 'source': 'builtin'})
    return result


def builtin_catalog():
    return [{'province': item['province'], 'operator': item['operator'],
             'channels': len(item['channels'])} for item in builtin_templates()]


def normalize_proxy_url(value):
    """Only public IP literals are allowed, including for subsequent deep checks."""
    from .safe_http import validate_ip_address

    try:
        if not isinstance(value, str) or len(value) > 256 or any(char.isspace() for char in value):
            raise ValueError
        parsed = urlsplit(value)
        address = ipaddress.ip_address(validate_ip_address(parsed.hostname))
        if (parsed.scheme not in ('http', 'https') or not address.is_global
                or address.is_multicast or parsed.username or parsed.password
                or parsed.query or parsed.fragment or '%' in parsed.netloc
                or not re.fullmatch(r'(?:/[A-Za-z0-9_-]+)*/?', parsed.path)):
            raise ValueError
        port = parsed.port if parsed.port is not None else (443 if parsed.scheme == 'https' else 80)
        if not 1 <= port <= 65535:
            raise ValueError
        host = f'[{address}]' if address.version == 6 else str(address)
        return f'{parsed.scheme}://{host}:{port}{parsed.path.rstrip("/")}'
    except (ValueError, TypeError):
        raise ValueError('代理地址需为公网 IP 的 HTTP(S) 基础地址，不能含账号、查询参数或播放路径') from None


def parse_manual_proxies(value):
    if not isinstance(value, str) or len(value) > 64_000:
        raise ValueError('手动组播代理需为最多 64000 字符的文本')
    proxies, seen = [], set()
    for line_number, line in enumerate(value.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.replace('，', ',').split(',')
        if len(parts) != 3:
            raise ValueError(f'代理第 {line_number} 行需填写：省份,运营商,HTTP(S)基础地址')
        province, operator = normalize_province(parts[0]), normalize_operator(parts[1])
        if not province or not operator:
            raise ValueError(f'代理第 {line_number} 行的省份或运营商无效')
        url = normalize_proxy_url(parts[2].strip())
        key = province, operator, url
        if key not in seen:
            seen.add(key)
            proxies.append({'province': province, 'operator': operator, 'url': url,
                            'platform': 'UDPXY', 'origin': 'udpxy', 'city': ''})
        if len(proxies) > 200:
            raise ValueError('手动组播代理最多允许 200 条')
    return proxies


def validate_config(cfg):
    """Validate before persistence so malformed edits are never silently discarded."""
    for key in ('multicast_enabled', 'multicast_use_builtin'):
        if key in cfg and not isinstance(cfg[key], bool):
            raise ValueError('组播开关必须为布尔值')
    for key, maximum in (('multicast_max_proxies', 50),
                         ('multicast_max_channels', 2000)):
        if key in cfg and (type(cfg[key]) is not int or not 1 <= cfg[key] <= maximum):
            raise ValueError(f'组播预算必须为 1 到 {maximum} 之间的整数')
    if 'multicast_proxy_urls' in cfg:
        parse_manual_proxies(cfg['multicast_proxy_urls'])
    if 'multicast_templates' not in cfg:
        return
    templates = cfg['multicast_templates']
    if not isinstance(templates, list) or len(templates) > MAX_CUSTOM_TEMPLATES:
        raise ValueError('自定义组播模板最多允许 32 组')
    seen, total = set(), 0
    for index, item in enumerate(templates, 1):
        if not isinstance(item, dict):
            raise ValueError(f'组播模板 {index} 格式错误')
        key = normalize_province(item.get('province')), normalize_operator(item.get('operator'))
        if not all(key) or key in seen:
            raise ValueError(f'组播模板 {index} 的省份/运营商无效或重复')
        seen.add(key)
        content = item.get('content')
        if not parse_playlist(content):
            raise ValueError(f'组播模板 {index} 没有有效频道，请填写含 rtp:// 或 udp:// 组播地址的 TXT/M3U')
        total += len(content)
        if total > 512_000:
            raise ValueError('自定义组播模板合计最多允许 512000 字符')


def selected_templates(cfg, provinces):
    groups = {}
    if cfg.get('multicast_use_builtin', True):
        groups.update({(item['province'], item['operator']): item for item in builtin_templates()})
    for item in cfg.get('multicast_templates', []):
        key = normalize_province(item.get('province')), normalize_operator(item.get('operator'))
        groups[key] = {'province': key[0], 'operator': key[1],
                       'channels': parse_playlist(item.get('content', '')), 'source': 'custom'}
    requested = {normalize_province(province) for province in provinces if province}
    if '' in requested:
        return {}
    requested.discard('')
    operator = normalize_operator(cfg.get('operator'))
    if cfg.get('operator') and not operator:
        return {}
    return {key: value for key, value in groups.items()
            if all(key) and value['channels'] and (not requested or key[0] in requested)
            and (not operator or key[1] == operator)}

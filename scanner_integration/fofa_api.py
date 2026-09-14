"""FOFA HTTPS API contract: https://fofa.info/api and /api/info."""

import asyncio
import re
import time
import weakref

import aiohttp

_session_limits = weakref.WeakKeyDictionary()


async def _pace_request(session, key):
    # Quality profiles share a session and may search concurrently. FOFA
    # recommends fewer than two requests/second for an individual account.
    limits = _session_limits.setdefault(session, {})
    state = limits.setdefault(key, {'lock': asyncio.Lock(), 'next': 0})
    async with state['lock']:
        delay = state['next'] - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
        state['next'] = time.monotonic() + 0.6


def with_fofa_filters(query, province=None, operator=None):
    """Use FOFA's documented region/org fields, never other vendors' isp."""
    aliases = {
        '电信': ('CHINANET', 'China Telecom', '电信'),
        '联通': ('UNICOM', '联通'),
        '移动': ('CMNET', 'China Mobile', '移动'),
        '广电': ('China Broadcasting', 'CHINA BROADNET', '广电'),
    }
    def quote(value):
        return str(value).replace('\\', '\\\\').replace('"', '\\"')

    clauses = [f'({query})']
    if province:
        clauses.append(f'region="{quote(province)}"')
    if operator:
        names = aliases.get(operator, (operator,))
        clauses.append('(' + ' || '.join(f'org="{quote(name)}"' for name in names) + ')')
    return ' && '.join(clauses) if province or operator else query


class FofaAPIError(Exception):
    def __init__(self, message, *, depleted=False, rotate_key=False):
        super().__init__(message)
        self.depleted = depleted
        self.rotate_key = rotate_key or depleted


def fofa_error_code(data):
    code = data.get('code')
    if code is not None:
        return str(code)
    match = re.search(r'\[(\d+)\]', str(data.get('errmsg') or data.get('message') or ''))
    return match.group(1) if match else None


def fofa_points_insufficient(data):
    message = str(data.get('errmsg') or data.get('message') or '')
    return fofa_error_code(data) == '820031' or bool(re.search(
        r'F\s*点.{0,12}(?:不足|耗尽|用完)|insufficient\s+fofa\s*points?', message, re.I,
    ))


FOFA_POINTS_HINT = '本次请求所需 F 点不足，不代表免费/月度 API 额度全部耗尽；请核对剩余次数、数据条数、单次请求数量及当前查询权益'


def _error_message(data, status, key):
    message = str(data.get('errmsg') or data.get('message') or f'HTTP {status}')
    # Provider errors can echo a query URL containing the credential.
    message = message.replace(key, '[redacted]') if key else message
    return message[:300]


async def request_fofa(session, endpoint, key, **params):
    """Use key-only auth; retry transient failures without logging query URLs."""
    for attempt in range(3):
        try:
            await _pace_request(session, key.strip())
            async with session.get(
                f'https://fofa.info/api/v1/{endpoint}',
                params={'key': key.strip(), **params},
                timeout=aiohttp.ClientTimeout(total=15),
                allow_redirects=False,
            ) as response:
                if response.status == 429 or response.status >= 500:
                    if attempt < 2:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    raise FofaAPIError(f'FOFA 请求失败 HTTP {response.status}，请稍后重试')
                try:
                    data = await response.json(content_type=None)
                except (ValueError, aiohttp.ClientError):
                    raise FofaAPIError(f'FOFA 返回非 JSON 响应 (HTTP {response.status})') from None
                if not isinstance(data, dict):
                    raise FofaAPIError('FOFA 返回数据格式异常')
                if response.status != 200 or data.get('error') is not False:
                    message = _error_message(data, response.status, key.strip())
                    points_insufficient = fofa_points_insufficient(data)
                    # HTTP 403 alone means forbidden, not necessarily exhausted credit.
                    depleted = not points_insufficient and bool(re.search(
                        r'(?:余额|积分|F点|F币|额度).{0,12}(?:不足|耗尽|用完)|'
                        r'insufficient (?:fofa\s*)?(?:credits?|points?|fcoins?|balance)|'
                        r'(?:quota|credits?|points?).{0,12}(?:exhausted|depleted)',
                        message, re.IGNORECASE,
                    ))
                    if points_insufficient:
                        message = f'{message}；{FOFA_POINTS_HINT}'
                    raise FofaAPIError(message, depleted=depleted, rotate_key=points_insufficient)
                return data
        except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
            if attempt == 2:
                reason = '请求超时' if isinstance(exc, asyncio.TimeoutError) else '网络连接失败'
                raise FofaAPIError(f'FOFA {reason}') from None
            await asyncio.sleep(2 ** attempt)

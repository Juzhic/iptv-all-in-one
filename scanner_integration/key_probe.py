"""Explicit, single-key diagnostics. No collection, retries or key rotation."""
import asyncio
import base64
import re
import time
from datetime import datetime, timezone

import aiohttp

from .config_bridge import build_search_queries
from .network import get_session


def _redact(value, key):
    text = str(value or '').replace(key, '***') if key else str(value or '')
    text = re.sub(r'(?i)((?:api[-_]?key|token|authorization)["\s:=]+)[^\s&,"}]+', r'\1***', text)
    return text[:400]


def _failure_state(status, message):
    if status == 429:
        return 'rate_limited'
    if status >= 500:
        return 'unavailable'
    if re.search(r'(?:key|token|密钥).{0,16}(?:invalid|expired|无效|失效|错误|不存在|不正确)|'
                 r'(?:invalid|expired).{0,16}(?:key|token)|认证失败|鉴权失败', message, re.I) or status == 401:
        return 'auth_failed'
    if re.search(r'(?:积分|余额|额度|F点|F币).{0,15}(?:不足|耗尽|用完)|'
                 r'insufficient (?:credits?|points?|balance)|quota.{0,15}(?:exhausted|exceeded)', message, re.I):
        return 'quota_exhausted'
    if status == 403 or re.search(r'无.{0,8}权限|没有权限|付费账号|升级.{0,8}会员|permission|forbidden', message, re.I):
        return 'permission_denied'
    return 'api_error'


async def _step(session, platform, kind, method, endpoint, key, **kwargs):
    started = time.monotonic()
    result = {'kind': kind, 'endpoint': endpoint, 'method': method.upper(),
              'state': 'unknown', 'http_status': None, 'code': None}
    try:
        async with getattr(session, method)(
            endpoint, **kwargs, allow_redirects=False,
            timeout=aiohttp.ClientTimeout(total=10, connect=3),
        ) as response:
            result['http_status'] = response.status
            try:
                data = await response.json(content_type=None)
            except (ValueError, aiohttp.ClientError):
                result.update(state='unknown', message='返回非 JSON 内容，无法判断 Key 是否有效')
                return result
            if not isinstance(data, dict):
                result.update(state='unknown', message='响应格式异常，无法判断 Key 是否有效')
                return result
            result['code'] = _redact(data.get('code', data.get('error')), key)
            message = _redact(data.get('message') or data.get('errmsg') or data.get('msg'), key)
            success = (data.get('error') is False if platform == 'fofa' else
                       str(data.get('code')) in ({'0'} if platform == 'quake' else {'0', '200', '2000'}))
            if response.status != 200 or not success:
                result.update(state=_failure_state(response.status, message),
                              message=message or f'HTTP {response.status}，平台未确认成功')
                return result
            if kind == 'search':
                inner = data.get('data')
                rows = (data.get('results') if platform == 'fofa' else inner if platform == 'quake' else
                        inner.get('arr' if platform == 'hunter' else 'list') if isinstance(inner, dict) else None)
                if not isinstance(rows, list):
                    result.update(state='unknown', message='平台返回成功码，但搜索结果结构异常，无法确认可用性')
                    return result
                result['returned_count'] = len(rows)
                result.update(state='passed', message='真实搜索成功' if rows else '真实搜索成功，零匹配结果不代表 Key 失效')
            elif platform != 'fofa' and not isinstance(data.get('data'), dict):
                result.update(state='unknown', message='账号响应结构异常，无法确认认证结果')
            else:
                result.update(state='passed', message='账号接口认证成功；搜索权限见下一项')
    except asyncio.TimeoutError:
        result.update(state='unknown', message='请求超时，无法判断 Key 是否失效')
    except (aiohttp.ClientError, OSError):
        result.update(state='unknown', message='网络连接失败，无法判断 Key 是否失效')
    except Exception:
        # Client exception text can include a credential-bearing request URL.
        result.update(state='unknown', message='接口测试异常，无法判断 Key 是否失效')
    finally:
        result['elapsed_ms'] = round((time.monotonic() - started) * 1000)
    return result


async def probe_key(platform, key, config, session=None):
    if platform not in ('hunter', 'quake', 'fofa', 'daydaymap'):
        raise ValueError('不支持的平台')
    if session is None:
        async with get_session(limit=2, timeout=10, force_close=True) as owned:
            return await probe_key(platform, key, config, owned)
    query = build_search_queries(config)[platform]
    steps = []
    if platform == 'hunter':
        steps.append(await _step(session, platform, 'account', 'get',
            'https://hunter.qianxin.com/openApi/userInfo', key, params={'api-key': key}))
        await asyncio.sleep(0.8)
        search = await _step(session, platform, 'search', 'get',
            'https://hunter.qianxin.com/openApi/search', key, params={
                'api-key': key, 'search': base64.urlsafe_b64encode(query.encode()).decode(),
                'page': 1, 'page_size': 1, 'is_web': 1})
    elif platform == 'fofa':
        steps.append(await _step(session, platform, 'account', 'get',
            'https://fofa.info/api/v1/info/my', key, params={'key': key}))
        await asyncio.sleep(0.8)
        search = await _step(session, platform, 'search', 'get',
            'https://fofa.info/api/v1/search/all', key, params={'key': key,
                'qbase64': base64.b64encode(query.encode()).decode(), 'page': 1, 'size': 1, 'fields': 'ip,port,region,city'})
    elif platform == 'quake':
        headers = {'X-QuakeToken': key, 'Content-Type': 'application/json'}
        steps.append(await _step(session, platform, 'account', 'get',
            'https://quake.360.net/api/v3/user/info', key, headers=headers))
        await asyncio.sleep(0.8)
        search = await _step(session, platform, 'search', 'post',
            'https://quake.360.net/api/v3/search/quake_service', key, headers=headers,
            json={'query': query, 'start': 0, 'size': 1, 'latest': True})
    else:
        steps.append({'kind': 'account', 'state': 'skipped', 'endpoint': '', 'method': '',
                      'http_status': None, 'code': None, 'elapsed_ms': 0,
                      'message': 'DayDayMap 网页账号接口需要登录令牌；直接用搜索接口验证 API Key'})
        search = await _step(session, platform, 'search', 'post',
            'https://www.daydaymap.com/api/v1/raymap/search/all', key,
            headers={'api-key': key, 'Content-Type': 'application/json'}, json={
                'keyword': base64.b64encode(query.encode()).decode(), 'page': 1, 'page_size': 1})
    steps.append(search)
    labels = {'passed': '可用：真实搜索成功', 'auth_failed': '搜索认证失败：Key 无效或已失效',
              'permission_denied': '搜索权限受限：不能据此认定 Key 失效',
              'quota_exhausted': '搜索额度不足：当前无法查询', 'rate_limited': '请求被限流：稍后重试',
              'unavailable': '平台服务异常：暂时无法判断', 'unknown': '暂时无法判断 Key 是否有效',
              'api_error': '搜索被拒绝：请查看平台错误原因'}
    return {'state': search['state'], 'usable': True if search['state'] == 'passed' else
            False if search['state'] in ('auth_failed', 'permission_denied', 'quota_exhausted') else None,
            'summary': labels[search['state']], 'steps': steps, 'query': _redact(query, key),
            'tested_at': datetime.now(timezone.utc).isoformat(), 'requested_size': 1}

"""Hunter account diagnostics and search error semantics shared by collectors."""
import re


def hunter_error(endpoint, status, payload, key=''):
    """Keep the failing endpoint/code, without exposing the credential."""
    payload = payload if isinstance(payload, dict) else {}
    message = str(payload.get('message') or payload.get('msg') or '请求失败')
    if key:
        message = message.replace(key, '***')
    message = re.sub(r'(?i)(api[-_]key[=:\s]+)[^\s&]+', r'\1***', message)
    code = payload.get('code', '-')
    return f'Hunter /openApi/{endpoint} HTTP {status}，code={code}：{message[:300]}'


def hunter_depleted(payload):
    """403 can mean permission denied; only explicit quota errors mean depleted."""
    if not isinstance(payload, dict):
        return False
    message = str(payload.get('message') or payload.get('msg') or '').lower()
    return any(term in message for term in (
        '积分不足', '积分耗尽', '余额不足', '额度耗尽', 'quota exhausted',
        'insufficient points',
    ))


async def read_hunter_response(response, endpoint, key=''):
    from .platforms.shared import KeyDepletedError
    try:
        payload = await response.json(content_type=None)
    except (ValueError, TypeError):
        payload = {}
    if (response.status == 200 and isinstance(payload, dict)
            and str(payload.get('code')) in ('0', '200', '2000')
            and isinstance(payload.get('data'), dict)):
        return payload['data']
    message = hunter_error(endpoint, response.status, payload, key)
    if hunter_depleted(payload):
        raise KeyDepletedError(message)
    raise ValueError(message)

# -*- coding: utf-8 -*-
"""
多 Key 轮换管理器。
支持每个平台配置多个 API Key，自动轮换积分耗尽的 key。
"""
import asyncio
import aiohttp
import json
import math
from .logger_bridge import logger


def _safe_number(value):
    """Return a finite number, or None for API placeholders like 'Invalid Number'."""
    if value is None or value == '':
        return None
    try:
        num = float(str(value).replace(',', '').strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(num):
        return None
    return int(num) if num.is_integer() else num


def _first_number(data, names):
    if not isinstance(data, dict):
        return None
    for name in names:
        value = data.get(name)
        num = _safe_number(value)
        if num is not None:
            return num
    return None


class KeyManager:
    """多 Key 轮换管理器（单例）。"""

    _instance = None

    def __init__(self):
        self._credits = {}   # {platform: {key: credit_amount}}
        self._keys = {}      # {platform: [key1, key2, ...]}

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def load_keys(self, platform, keys):
        """加载某平台的 key 列表。"""
        keys = [k.strip() for k in (keys or []) if k and k.strip()]
        self._keys[platform] = keys
        for k in keys:
            if platform not in self._credits:
                self._credits[platform] = {}
            if k not in self._credits[platform]:
                self._credits[platform][k] = float('inf')  # 未知状态，假设可用

    def get_key(self, platform):
        """返回该平台一个可用 key（余额最多优先）。"""
        keys = self._keys.get(platform, [])
        if not keys:
            return ''
        credits = self._credits.get(platform, {})
        # 按 credit 降序排列，选第一个 > 0 的
        sorted_keys = sorted(keys, key=lambda k: credits.get(k, 0), reverse=True)
        best = sorted_keys[0] if sorted_keys else ''
        best_credit = credits.get(best, 0)
        if best_credit <= 0:
            # 所有 key 都 depleted，返回第一个让用户看到错误
            logger.warning(f"[KeyMgr] {platform} 所有 key 积分耗尽，使用第一个 key")
            return keys[0]
        return best

    def get_all_keys(self, platform):
        """返回该平台所有 key。"""
        return self._keys.get(platform, [])

    def mark_depleted(self, platform, key):
        """标记某个 key 积分耗尽（收到 403 时调用）。"""
        if platform not in self._credits:
            self._credits[platform] = {}
        self._credits[platform][key] = 0
        remaining = sum(1 for k in self._keys.get(platform, [])
                        if self._credits.get(platform, {}).get(k, 0) > 0)
        logger.warning(f"[KeyMgr] {platform} key ...{key[-4:]} 已耗尽，"
                       f"剩余可用: {remaining}")

    def update_credit(self, platform, key, credit):
        """更新某个 key 的积分余额。"""
        if platform not in self._credits:
            self._credits[platform] = {}
        self._credits[platform][key] = credit

    def get_credits_info(self, platform):
        """返回该平台所有 key 的积分信息。"""
        keys = self._keys.get(platform, [])
        credits = self._credits.get(platform, {})
        return {k: credits.get(k, None) for k in keys}

    def reset(self):
        """重置所有状态。"""
        self._credits.clear()
        self._keys.clear()


def get_keys_from_config(platform):
    """从配置读取某平台的 key 列表（兼容旧格式）。"""
    from . import config_bridge
    cfg = config_bridge.get_scan_config()

    # 新格式：列表
    keys_list = cfg.get(f'{platform}_api_keys', [])
    if keys_list and isinstance(keys_list, list):
        return [k.strip() for k in keys_list if k and k.strip()]

    # 兼容旧格式：单个字符串
    single = cfg.get(f'{platform}_api_key', '')
    if single and isinstance(single, str) and single.strip():
        return [single.strip()]

    return []


def init_key_manager():
    """从配置初始化 KeyManager。"""
    km = KeyManager.instance()
    for platform in ('quake', 'hunter', 'daydaymap'):
        keys = get_keys_from_config(platform)
        km.load_keys(platform, keys)
        logger.info(f"[KeyMgr] {platform}: {len(keys)} 个 key")
    return km


async def check_quake_credit(api_key):
    """查询单个 Quake key 的积分。返回 dict 或 None。"""
    try:
        headers = {"X-QuakeToken": api_key}
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
            async with s.get("https://quake.360.net/api/v3/user/info",
                             headers=headers) as resp:
                data = await resp.json()
                if data.get('code') != 0:
                    return {'error': data.get('message', '查询失败')}
                d = data.get('data', {})
                roles = d.get('role', [])
                return {
                    'ok': True,
                    'credit': d.get('credit', 0),
                    'month_remaining': d.get('month_remaining_credit', 0),
                    'role': roles[0].get('fullname', '') if roles else '',
                    'role_limit': roles[0].get('credit', 0) if roles else 0,
                }
    except Exception as e:
        return {'error': str(e)}


async def check_hunter_credit(api_key):
    """Query Hunter openApi userInfo to get remaining points.
    Uses api-key parameter (openApi format).
    Response: data.rest_free_point (remaining), data.personal_info.user_name
    """
    try:
        key = api_key.strip()
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
            # 1) openApi/userInfo — 直接返回剩余积分
            try:
                url = "https://hunter.qianxin.com/openApi/userInfo"
                async with s.get(url, params={"api-key": key}) as resp:
                    print(f"[Hunter] userInfo status={resp.status}")
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        print(f"[Hunter] RAW: {json.dumps(data, ensure_ascii=False)[:500]}")
                        d = data.get('data') or {}
                        if isinstance(d, dict) and str(data.get('code')) in ('0', '200', '2000'):
                            points = _first_number(d, (
                                'rest_free_point', 'rest_equity_point',
                            ))
                            day_limit = _first_number(d, ('day_free_point',))
                            personal = d.get('personal_info') or {}
                            role = (personal.get('user_name', '')
                                    if isinstance(personal, dict) else '')
                            logger.info(f"[Hunter] points={points} day_limit={day_limit}")
                            return {
                                'ok': True,
                                'points': points,
                                'day_limit': day_limit,
                                'role': role,
                            }
                        else:
                            print(f"[Hunter] userInfo unexpected: code={data.get('code')}")
                    else:
                        print(f"[Hunter] userInfo HTTP {resp.status}")
            except Exception as e:
                print(f"[Hunter] userInfo exception: {e}")

            # 2) 回退：openApi/search 最小查询，从 rest_quota 解析
            try:
                import base64
                dummy_query = base64.urlsafe_b64encode(b'test').decode().rstrip('=')
                async with s.get("https://hunter.qianxin.com/openApi/search",
                                 params={"api-key": key, "search": dummy_query,
                                         "page": 1, "page_size": 1, "is_web": 1},
                                 timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    print(f"[Hunter] search fallback status={resp.status}")
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        d = data.get('data') or {}
                        if isinstance(d, dict) and str(data.get('code')) in ('0', '200', '2000'):
                            rq = str(d.get('rest_quota', ''))
                            import re
                            m = re.search(r'(\d+)', rq)
                            points = int(m.group(1)) if m else None
                            print(f"[Hunter] search rest_quota={rq} -> points={points}")
                            return {'ok': True, 'points': points, 'role': ''}
                        print(f"[Hunter] search unexpected: code={data.get('code')}")
                        return {'error': data.get('message', 'query failed')}
                    elif resp.status == 403:
                        return {'ok': True, 'points': 0, 'role': '',
                                'error': '积分耗尽 (HTTP 403)'}
                    return {'error': f'HTTP {resp.status}'}
            except Exception as e:
                print(f"[Hunter] search fallback exception: {e}")
                return {'error': f'userInfo+search both failed: {e}'}
    except Exception as e:
        print(f"[Hunter] check_hunter_credit fatal: {e}")
        return {'error': str(e)}


async def check_daydaymap_credit(api_key, query=None):
    """Query DayDayMap credit / validate API key.
    The bffapi user-info endpoint requires a Bearer token (JWT from web login),
    which is different from the api-key used for scanning.
    Fallback: do a minimal search with the real query to verify key validity.
    """
    try:
        key = api_key.strip()
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
            # 1) 尝试 bffapi user/info/query（需要 Bearer token，api-key 大概率不支持）
            try:
                auth_value = key if key.lower().startswith("bearer ") else f"Bearer {key}"
                bff_headers = {
                    "Authorization": auth_value,
                    "api-key": key,
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Origin": "https://www.daydaymap.com",
                    "Referer": "https://www.daydaymap.com/",
                }
                async with s.post(
                    "https://www.daydaymap.com/bffapi/v1/user/info/query",
                    headers=bff_headers, json={}) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        d = data.get('data')
                        code = data.get('code')
                        if d and isinstance(d, dict) and str(code) in ('0', '200', '2000'):
                            free_score = _first_number(d, (
                                'freeUsableScore', 'free_usable_score',
                                'dailyUsableScore', 'daily_usable_score',
                                'freeScore', 'free_score',
                            ))
                            paid_score = _first_number(d, (
                                'paidUsableScore', 'paid_usable_score',
                                'equityUsableScore', 'equity_usable_score',
                                'paidScore', 'paid_score',
                            ))
                            fallback_score = _first_number(d, (
                                'usableScore', 'usable_score',
                                'remainingScore', 'remaining_score',
                                'balance', 'points', 'score', 'credit',
                            ))
                            if free_score is not None or paid_score is not None:
                                credit = (free_score or 0) + (paid_score or 0)
                            else:
                                credit = fallback_score
                            role = (d.get('vipLevel') or d.get('vip_level')
                                    or d.get('username') or d.get('userName') or '')
                            return {
                                'ok': True, 'credit': credit,
                                'free_score': free_score, 'paid_score': paid_score,
                                'role': role,
                            }
            except Exception:
                pass

            # 2) 回退：用 scan API 最小查询验证 key 有效性
            #    需要用真实的查询语法，不能用 dummy
            if not query:
                from . import config_bridge
                query = config_bridge.get_scan_config().get(
                    'daydaymap_query', config_bridge.DAYDAYMAP_QUERY)
            import base64
            keyword_b64 = base64.b64encode(query.encode()).decode()
            scan_headers = {"api-key": key, "Content-Type": "application/json"}
            async with s.post(
                "https://www.daydaymap.com/api/v1/raymap/search/all",
                headers=scan_headers,
                json={"page": 1, "page_size": 1, "keyword": keyword_b64},
                timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    code = data.get('code')
                    if code == 200:
                        # Key 有效；API 不返回余额，标记为有效
                        d = data.get('data') or {}
                        total = _first_number(d, ('total',))
                        return {
                            'ok': True,
                            'credit': None,  # 无法通过 API key 查询具体余额
                            'free_score': None,
                            'paid_score': None,
                            'role': f'有效 (共{total}条)' if total else '有效',
                        }
                    msg = data.get('msg') or data.get('message') or ''
                    return {'error': msg or f'API code={code}'}
                elif resp.status == 403:
                    return {'ok': True, 'credit': 0, 'free_score': None,
                            'paid_score': None, 'role': '',
                            'error': '积分耗尽 (HTTP 403)'}
                return {'error': f'HTTP {resp.status}'}
    except Exception as e:
        return {'error': str(e)}


async def check_all_quake_credits():
    """查询所有 Quake key 的积分。"""
    km = KeyManager.instance()
    keys = km.get_all_keys('quake')
    results = []
    for key in keys:
        info = await check_quake_credit(key)
        credit = _safe_number(info.get('month_remaining')) if info.get('ok') else 0
        role_limit = _safe_number(info.get('role_limit'))
        km.update_credit('quake', key, credit if credit is not None else 0)
        results.append({
            'key_suffix': f"...{key[-6:]}",
            'credit': credit,
            'role': info.get('role', ''),
            'role_limit': role_limit,
            'error': info.get('error', ''),
        })
    return results


async def check_all_hunter_credits():
    """Query all Hunter key/token points."""
    km = KeyManager.instance()
    keys = km.get_all_keys('hunter')
    results = []
    for key in keys:
        info = await check_hunter_credit(key)
        print(info)
        credit = _safe_number(info.get('points')) if info.get('ok') else None
        if credit is not None:
            km.update_credit('hunter', key, credit)
        results.append({
            'key_suffix': f"...{key[-6:]}",
            'credit': credit,
            'role': info.get('role', ''),
            'role_limit': None,
            'error': info.get('error', ''),
        })
    return results


async def check_all_daydaymap_credits():
    """Query all DayDayMap key/token points."""
    km = KeyManager.instance()
    keys = km.get_all_keys('daydaymap')
    results = []
    for key in keys:
        info = await check_daydaymap_credit(key)
        credit = _safe_number(info.get('credit')) if info.get('ok') else None
        if credit is not None:
            km.update_credit('daydaymap', key, credit)
        results.append({
            'key_suffix': f"...{key[-6:]}",
            'credit': credit,
            'role': info.get('role', ''),
            'role_limit': None,
            'error': info.get('error', ''),
        })
    return results

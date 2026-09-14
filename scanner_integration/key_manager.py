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
from engine.utils import safe_number as _safe_number


def _credit_rank(value):
    if value is None or value == -1:
        return float('inf')
    try:
        return float(value)
    except (TypeError, ValueError):
        return float('inf')


def _credit_is_usable(value):
    return _credit_rank(value) > 0


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
        sorted_keys = sorted(keys, key=lambda k: _credit_rank(credits.get(k)), reverse=True)
        best = sorted_keys[0] if sorted_keys else ''
        best_credit = credits.get(best)
        if not _credit_is_usable(best_credit):
            # 所有 key 都 depleted，返回第一个让用户看到错误
            logger.warning(f"[KeyMgr] {platform} 所有 key 积分耗尽，使用第一个 key")
            return keys[0]
        return best

    def get_all_keys(self, platform):
        """返回该平台所有 key。"""
        return self._keys.get(platform, [])

    def mark_depleted(self, platform, key):
        """标记某个 key 积分耗尽（平台明确报告额度不足时调用）。"""
        if platform not in self._credits:
            self._credits[platform] = {}
        self._credits[platform][key] = 0
        remaining = sum(1 for k in self._keys.get(platform, [])
                        if _credit_is_usable(self._credits.get(platform, {}).get(k)))
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
    for platform in ('quake', 'hunter', 'daydaymap', 'fofa'):
        keys = get_keys_from_config(platform)
        km.load_keys(platform, keys)
        logger.info(f"[KeyMgr] {platform}: {len(keys)} 个 key")
    return km


async def check_quake_credit(api_key, session=None):
    """查询单个 Quake key 的积分。返回 dict 或 None。"""
    own_session = session is None
    if own_session:
        from .network import get_session
        session = get_session(limit=5, timeout=15)
    try:
        headers = {"X-QuakeToken": api_key}
        async with session.get("https://quake.360.net/api/v3/user/info",
                         headers=headers) as resp:
            logger.debug(f"[Quake] user/info status={resp.status}")
            if resp.status != 200:
                text = await resp.text()
                logger.warning(f"[Quake] user/info HTTP {resp.status}: {text[:300]}")
                return {'error': f'HTTP {resp.status}'}
            data = await resp.json()
            logger.debug(f"[Quake] RAW: {json.dumps(data, ensure_ascii=False)[:500]}")
            # 兼容 code 为 0 或 "0" 或 "200" 或 "success"
            code = data.get('code')
            if str(code) not in ('0', '200', 'success'):
                return {'error': data.get('message', f'查询失败 (code={code})')}
            d = data.get('data', {})
            if not isinstance(d, dict):
                return {'error': f'返回 data 格式异常: {type(d)}'}
            roles = d.get('role', [])
            # 兼容多种字段名：month_remaining_credit / month_remaining_data / remaining_credit
            month_remaining = _first_number(d, (
                'month_remaining_credit', 'month_remaining_data',
                'remaining_credit', 'month_remaining', 'credit',
            ))
            # 如果 month_remaining 没取到，退回 credit 字段
            if month_remaining is None:
                month_remaining = _safe_number(d.get('credit', 0)) or 0
            role_name = ''
            role_limit = 0
            if isinstance(roles, list) and roles:
                role_name = roles[0].get('fullname', '') if isinstance(roles[0], dict) else str(roles[0])
                role_limit = _safe_number(roles[0].get('credit', 0)) if isinstance(roles[0], dict) else 0
            logger.info(f"[Quake] credit={month_remaining} role={role_name} role_limit={role_limit}")
            return {
                'ok': True,
                'credit': _safe_number(d.get('credit', 0)) or 0,
                'month_remaining': month_remaining,
                'role': role_name,
                'role_limit': role_limit,
            }
    except asyncio.TimeoutError:
        logger.warning("[Quake] user/info 请求超时 (15s)")
        return {'error': '请求超时'}
    except Exception as e:
        logger.warning(f"[Quake] check_quake_credit fatal: {e}")
        return {'error': str(e)}
    finally:
        if own_session:
            await session.close()


async def check_hunter_credit(api_key, session=None):
    """Read account balances only; never spend search quota to check a key."""
    from .hunter_api import read_hunter_response
    from .platforms.shared import KeyDepletedError
    own_session = session is None
    if own_session:
        from .network import get_session
        session = get_session(limit=5, timeout=15)
    try:
        key = api_key.strip()
        async with session.get(
            "https://hunter.qianxin.com/openApi/userInfo",
            params={"api-key": key}, allow_redirects=False,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            d = await read_hunter_response(resp, 'userInfo', key)
        free = _first_number(d, ('rest_free_point', 'free_point'))
        equity = _first_number(d, ('rest_equity_point',))
        # Missing pools are unknown, not zero. -1 means unlimited in Hunter docs.
        pools = [n for n in (free, equity) if n is not None]
        points = (-1 if -1 in pools else sum(pools)) if pools else None
        if points == 0 and (free is None or equity is None):
            points = None
        personal = d.get('personal_info') or {}
        return {
            'ok': True, 'points': points,
            'free_points': free, 'equity_points': equity,
            'day_limit': _first_number(d, ('day_free_point', 'daily_free_point')),
            'role': personal.get('username', personal.get('user_name', '')) if isinstance(personal, dict) else '',
        }
    except asyncio.TimeoutError:
        return {'error': 'Hunter /openApi/userInfo 请求超时 (15s)'}
    except (ValueError, KeyDepletedError) as exc:
        return {'error': str(exc)}
    except Exception as exc:
        # Client exceptions can contain request URLs with api-key query strings.
        return {'error': f'Hunter /openApi/userInfo 请求失败 ({type(exc).__name__})'}
    finally:
        if own_session:
            await session.close()


async def check_daydaymap_credit(api_key, query=None, session=None):
    """Query DayDayMap credit / validate API key.
    The bffapi user-info endpoint requires a Bearer token (JWT from web login),
    which is different from the api-key used for scanning.
    Fallback: do a minimal search with the real query to verify key validity.
    """
    own_session = session is None
    if own_session:
        from .network import get_session
        session = get_session(limit=5, timeout=15)
    try:
        key = api_key.strip()
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
            async with session.post(
                "https://www.daydaymap.com/bffapi/v1/user/info/query",
                headers=bff_headers, json={}) as resp:
                logger.debug(f"[DayDayMap] bffapi status={resp.status}")
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    logger.debug(f"[DayDayMap] RAW: {json.dumps(data, ensure_ascii=False)[:500]}")
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
                        logger.info(f"[DayDayMap] credit={credit} free={free_score} paid={paid_score} role={role}")
                        return {
                            'ok': True, 'credit': credit,
                            'free_score': free_score, 'paid_score': paid_score,
                            'role': role,
                        }
                else:
                    logger.debug(f"[DayDayMap] bffapi HTTP {resp.status}")
        except asyncio.TimeoutError:
            logger.debug("[DayDayMap] bffapi 请求超时 (15s)")
        except Exception:
            pass

        # 2) 回退：用 scan API 最小查询验证 key 有效性
        #    需要用真实的查询语法，不能用 dummy
        if not query:
            from . import config_bridge
            cfg = config_bridge.get_scan_config()
            query = config_bridge.build_search_queries(cfg)['daydaymap']
        import base64
        keyword_b64 = base64.b64encode(query.encode()).decode()
        scan_headers = {"api-key": key, "Content-Type": "application/json"}
        async with session.post(
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
    finally:
        if own_session:
            await session.close()


async def check_all_quake_credits():
    """查询所有 Quake key 的积分。"""
    from .network import get_session
    km = KeyManager.instance()
    keys = km.get_all_keys('quake')
    results = []
    async with get_session(limit=5, timeout=15) as session:
        for key in keys:
            info = await check_quake_credit(key, session=session)
            credit = _safe_number(info.get('month_remaining')) if info.get('ok') else 0
            role_limit = _safe_number(info.get('role_limit'))
            if info.get('ok') and credit is not None:
                km.update_credit('quake', key, credit)
            else:
                credit = None
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
    from .network import get_session
    km = KeyManager.instance()
    keys = km.get_all_keys('hunter')
    results = []
    async with get_session(limit=5, timeout=15) as session:
        for key in keys:
            info = await check_hunter_credit(key, session=session)
            credit = _safe_number(info.get('points')) if info.get('ok') else None
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
    from .network import get_session
    km = KeyManager.instance()
    keys = km.get_all_keys('daydaymap')
    results = []
    async with get_session(limit=5, timeout=15) as session:
        for key in keys:
            info = await check_daydaymap_credit(key, session=session)
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


async def check_fofa_credit(api_key, session=None):
    """Query account balances only; never spend search quota to check a key."""
    from .fofa_api import FofaAPIError, request_fofa
    from .network import get_session
    own_session = session is None
    if own_session:
        session = get_session(limit=5, timeout=15)
    try:
        async with asyncio.timeout(15):
            data = await request_fofa(session, 'info/my', api_key)
        balances = {
            name: _safe_number(data.get(name)) for name in (
                'fcoin', 'fofa_point', 'remain_free_point',
                'remain_api_query', 'remain_api_data',
            )
        }
        level = data.get('vip_level')
        return {
            'ok': True, 'credit': balances['fofa_point'],
            'balances': balances,
            'role': f'会员等级 {level}' if level is not None else '',
        }
    except FofaAPIError as exc:
        return {'error': str(exc)}
    except asyncio.TimeoutError:
        return {'error': 'FOFA 账号查询超时'}
    finally:
        if own_session:
            await session.close()


async def check_all_fofa_credits():
    """Keep F coins, points and monthly API quotas in their own units."""
    from .network import get_session
    km = KeyManager.instance()
    keys = km.get_all_keys('fofa')
    if not keys:
        return []
    results = []
    async with get_session(limit=5, timeout=15) as session:
        semaphore = asyncio.Semaphore(5)

        async def check(key, index):
            await asyncio.sleep(index * 0.6)
            async with semaphore:
                return await check_fofa_credit(key, session=session)

        tasks = [asyncio.create_task(check(key, index)) for index, key in enumerate(keys)]
        try:
            # The HTTP route has a 50-second bridge deadline. Preserve completed
            # accounts even when another key times out or there are many keys.
            await asyncio.wait(tasks, timeout=45)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        for key, task in zip(keys, tasks):
            if task.cancelled():
                info = {'error': 'FOFA 账号查询超时'}
            elif task.exception() is not None:
                info = {'error': 'FOFA 账号查询失败'}
            else:
                info = task.result()
            if info.get('ok'):
                # Account balances do not prove search eligibility; only an explicit
                # exhausted-search response should exclude this key from rotation.
                km.update_credit('fofa', key, None)
            results.append({
                'key_suffix': f"...{key[-6:]}",
                'credit': info.get('credit'),
                'balances': info.get('balances', {}),
                'verified': bool(info.get('ok')),
                'role': info.get('role', ''),
                'role_limit': None,
                'error': info.get('error', ''),
            })
    return results

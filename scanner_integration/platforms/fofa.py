# -*- coding: utf-8 -*-
"""Fofa 平台扫描模块。"""

import asyncio
import base64

import aiohttp

from . import config_bridge
from .config_bridge import API_REQUEST_DELAY
from .network import get_session
from .logger_bridge import logger
from .shared import KeyDepletedError, _is_stop_requested, _retry_with_backoff, _stats_add, _stats_set
from .ip_extract import extract_channels_from_ip, smart_c_segment_scan


async def fofa_scan(api_key=None, query=None, target_size=None, session=None, stats=None):
    """扫描 Fofa 平台。"""
    if api_key is None:
        api_key = config_bridge.get_scan_config().get("fofa_key", "")
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
    if target_size is None:
        target_size = config_bridge.get_scan_config().get("fofa_size", 200)
    _stats_set(stats, 'target_size', target_size)
    if session is None:
        session = get_session(limit=30, force_close=True)
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
                        if not results:
                            break
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
                            if lst:
                                collected_entries.extend(lst)
                        if len(results) < size:
                            break
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

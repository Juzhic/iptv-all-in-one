# -*- coding: utf-8 -*-
"""Quake 360 平台扫描模块。"""

import asyncio

import aiohttp

from .. import config_bridge
from ..config_bridge import API_REQUEST_DELAY
from ..network import get_session
from ..logger_bridge import logger
from .shared import KeyDepletedError, _is_stop_requested, _stats_add, _stats_set
from .ip_extract import extract_channels_from_ip, smart_c_segment_scan


async def quake_scan(api_key=None, query=None, target_size=None, session=None, stats=None):
    """扫描 Quake 360 平台。"""
    if api_key is None:
        api_key = config_bridge.get_scan_config().get("quake_key", "")
    if not api_key:
        logger.warning("[Quake] 未配置 API Key，跳过")
        return []
    if query is None:
        logger.warning("[Quake] 未提供搜索查询条件，跳过")
        return []
    if target_size is None:
        target_size = config_bridge.get_scan_config().get("quake_size", 200)
    _stats_set(stats, 'target_size', target_size)
    if session is None:
        session = get_session(limit=30, force_close=True)
    BATCH_SIZE = 50
    collected_entries, collected_success = [], []
    for start in range(0, target_size, BATCH_SIZE):
        if _is_stop_requested():
            logger.info("[Quake] 检测到中止请求，停止扫描")
            break
        size = min(BATCH_SIZE, target_size - start)
        try:
            await asyncio.sleep(API_REQUEST_DELAY * 0.5)
            async with session.post(
                "https://quake.360.net/api/v3/search/quake_service",
                headers={"X-QuakeToken": api_key, "Content-Type": "application/json"},
                json={"query": query, "start": start, "size": size, "latest": True},
                timeout=aiohttp.ClientTimeout(total=15)
            ) as r:
                if r.status == 200:
                    j = await r.json()
                    if j.get("code") == 0:
                        items = j.get("data", [])
                        if not items:
                            break
                        _stats_add(stats, 'api_items', len(items))
                        _stats_add(stats, 'probed_hosts', len(items))
                        logger.info(f"[Quake] 获取 {start}~{start+len(items)} 条")

                        async def f(item):
                            ch = await extract_channels_from_ip(
                                item.get("ip"), item.get("port", 8080), session,
                                (item.get("province", "") or (item.get("location", {}) or {}).get("province_cn", "")),
                                (item.get("city", "") or (item.get("location", {}) or {}).get("city_cn", ""))
                            )
                            if ch:
                                collected_success.append((item.get("ip"), item.get("port", 8080)))
                            return ch

                        for lst in await asyncio.gather(*[f(it) for it in items]):
                            if lst:
                                collected_entries.extend(lst)
                        if len(items) < size:
                            break
                elif r.status == 403:
                    raise KeyDepletedError("Quake key 积分耗尽")
                else:
                    logger.warning(f"[Quake] 请求失败 HTTP {r.status}")
                    break
        except KeyDepletedError:
            raise  # 让 key 耗尽冒泡到 _run_with_key_rotation 触发轮换
        except asyncio.TimeoutError:
            logger.warning(f"[Quake] 批次 {start} 超时")
            break
        except Exception as e:
            logger.warning(f"[Quake] 批次 {start} 失败: {e}")
            break
    logger.info(f"[Quake] 总共提取频道: {len(collected_entries)}")
    if config_bridge.get_scan_config().get("enable_c_scan") and collected_success:
        c_entries = await smart_c_segment_scan(collected_success, session, stats=stats)
        _stats_add(stats, 'c_segment_channels', len(c_entries))
        collected_entries.extend(c_entries)
    _stats_set(stats, 'extracted_channels', len(collected_entries))
    return collected_entries

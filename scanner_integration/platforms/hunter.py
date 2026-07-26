# -*- coding: utf-8 -*-
"""Hunter 平台扫描模块。"""

import asyncio
import base64

import aiohttp

from . import config_bridge
from .config_bridge import API_REQUEST_DELAY
from .network import get_session
from .logger_bridge import logger
from .shared import KeyDepletedError, _is_stop_requested, _stats_add, _stats_set
from .ip_extract import extract_channels_from_ip, smart_c_segment_scan


async def hunter_scan(api_key, query, target_size, session=None, stats=None):
    """扫描 Hunter 平台。"""
    if not api_key:
        logger.warning("[Hunter] 未配置 API Key，跳过")
        return []
    if session is None:
        session = get_session(limit=30, force_close=True)
    if target_size is None:
        target_size = config_bridge.get_scan_config().get("hunter_size", config_bridge.get_scan_config().get("quake_size", 200))
    MAX_PAGE_SIZE = 10
    _stats_set(stats, 'target_size', target_size)
    collected_entries = []
    collected_success = []
    page = 1
    BATCH_SIZE = MAX_PAGE_SIZE
    fetched_items = 0
    while fetched_items < target_size:
        if _is_stop_requested():
            logger.info("[Hunter] 检测到中止请求，停止扫描")
            break
        remaining = target_size - fetched_items
        size = min(BATCH_SIZE, remaining)
        page_size = max(1, min(MAX_PAGE_SIZE, size))
        try:
            await asyncio.sleep(API_REQUEST_DELAY * 0.5)
            qb = base64.urlsafe_b64encode(query.encode()).decode().rstrip('=')
            logger.info(f"[Hunter] 请求 page={page}, page_size={page_size}")
            async with session.get(
                "https://hunter.qianxin.com/openApi/search",
                params={
                    "api-key": api_key,
                    "search": qb,
                    "page": page,
                    "page_size": page_size,
                    "is_web": 1
                },
                timeout=aiohttp.ClientTimeout(total=15)
            ) as r:
                if r.status == 200:
                    j = await r.json()
                    if j.get("code") in (200, 0):
                        data = j.get("data") or {}
                        items = data.get("arr") or []
                        if not items:
                            break
                        fetched_items += len(items)
                        _stats_add(stats, 'api_items', len(items))
                        _stats_add(stats, 'probed_hosts', len(items))
                        logger.info(f"[Hunter] 第{page}页，{len(items)} 条")

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
                        if len(items) < page_size:
                            break
                        page += 1
                    else:
                        logger.warning(f"[Hunter] API 返回错误: {j.get('message')}, 完整响应: {j}")
                        break
                elif r.status == 403:
                    raise KeyDepletedError("Hunter key 积分耗尽")
                else:
                    logger.warning(f"[Hunter] 请求失败 HTTP {r.status}, 响应: {await r.text()}")
                    break
        except KeyDepletedError:
            raise  # 让 key 耗尽冒泡到 _run_with_key_rotation 触发轮换
        except asyncio.TimeoutError:
            logger.warning(f"[Hunter] 第{page}页超时")
            break
        except Exception as e:
            logger.warning(f"[Hunter] 批次 {page} 失败: {e}")
            break
    logger.info(f"[Hunter] 总共提取频道: {len(collected_entries)}")
    if config_bridge.get_scan_config().get("enable_c_scan") and collected_success:
        c_entries = await smart_c_segment_scan(collected_success, session)
        _stats_add(stats, 'c_segment_channels', len(c_entries))
        collected_entries.extend(c_entries)
    _stats_set(stats, 'extracted_channels', len(collected_entries))
    return collected_entries

# -*- coding: utf-8 -*-
"""Hunter 平台扫描模块。"""

import asyncio
import base64
from math import gcd

import aiohttp

from .. import config_bridge
from ..config_bridge import API_REQUEST_DELAY
from ..network import get_session
from ..hunter_api import read_hunter_response
from ..logger_bridge import logger
from .shared import KeyDepletedError, _is_stop_requested, _stats_add, _stats_set
from .ip_extract import extract_channels_from_ip, smart_c_segment_scan


async def hunter_scan(api_key, query, target_size, session=None, stats=None):
    """扫描 Hunter 平台。"""
    if not api_key:
        logger.warning("[Hunter] 未配置 API Key，跳过")
        return []
    if session is None:
        async with get_session(limit=30, force_close=True) as owned_session:
            return await hunter_scan(api_key, query, target_size, session=owned_session, stats=stats)
    if target_size is None:
        target_size = config_bridge.get_scan_config().get("hunter_size", config_bridge.get_scan_config().get("quake_size", 200))
    MAX_PAGE_SIZE = 10
    _stats_set(stats, 'target_size', target_size)
    collected_entries = []
    collected_success = []
    page = 1
    fetched_items = 0
    while fetched_items < target_size:
        if _is_stop_requested():
            logger.info("[Hunter] 检测到中止请求，停止扫描")
            break
        # Hunter uses (page - 1) * page_size as the offset. On a short tail,
        # choose a divisor of the offset and recompute page to avoid duplicates
        # without requesting rows beyond the configured budget.
        page_size = min(MAX_PAGE_SIZE, target_size - fetched_items)
        if fetched_items % page_size:
            page_size = gcd(fetched_items, page_size)
        page = fetched_items // page_size + 1
        try:
            await asyncio.sleep(API_REQUEST_DELAY * 0.5)
            qb = base64.urlsafe_b64encode(query.encode()).decode()
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
                allow_redirects=False, timeout=aiohttp.ClientTimeout(total=15)
            ) as r:
                data = await read_hunter_response(r, 'search', api_key)
                items = data.get("arr") or []
                if not items:
                    break
                received_count = len(items)
                items = items[:target_size - fetched_items]
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
                if received_count < page_size:
                    break
                page += 1
        except KeyDepletedError as exc:
            exc.partial_entries = collected_entries
            raise  # 让 key 耗尽冒泡到 _run_with_key_rotation 触发轮换
        except ValueError as exc:
            _stats_set(stats, 'skipped_reason', str(exc))
            logger.warning(str(exc))
            break
        except asyncio.TimeoutError:
            logger.warning(f"[Hunter] 第{page}页超时")
            break
        except Exception as e:
            logger.warning(f"[Hunter] 批次 {page} 失败: {type(e).__name__}")
            break
    logger.info(f"[Hunter] 总共提取频道: {len(collected_entries)}")
    if config_bridge.get_scan_config().get("enable_c_scan") and collected_success:
        c_entries = await smart_c_segment_scan(collected_success, session, stats=stats)
        _stats_add(stats, 'c_segment_channels', len(c_entries))
        collected_entries.extend(c_entries)
    _stats_set(stats, 'extracted_channels', len(collected_entries))
    return collected_entries

# -*- coding: utf-8 -*-
"""DayDayMap 平台扫描模块。"""

import asyncio
import base64

import aiohttp

from . import config_bridge
from .config_bridge import DAYDAYMAP_API_DELAY
from .network import get_session
from .logger_bridge import logger
from .shared import KeyDepletedError, _is_stop_requested, _stats_add, _stats_set
from .ip_extract import extract_channels_from_ip, smart_c_segment_scan


async def daydaymap_scan(api_key, query, target_size, session=None, stats=None):
    """扫描 DayDayMap 平台。"""
    if not api_key:
        logger.warning("[DayDayMap] 未配置 API Key，跳过")
        return []
    if session is None:
        session = get_session(limit=30, force_close=True)
    if target_size is None:
        target_size = config_bridge.get_scan_config().get("daydaymap_size", 200)
    _stats_set(stats, 'target_size', target_size)
    BATCH_SIZE = 50
    all_items = []
    headers = {"api-key": api_key, "Content-Type": "application/json"}
    keyword_base64 = base64.b64encode(query.encode()).decode()
    page = 1
    max_pages = max(1, (target_size + BATCH_SIZE - 1) // BATCH_SIZE)
    while len(all_items) < target_size and page <= max_pages:
        if _is_stop_requested():
            logger.info("[DayDayMap] 检测到中止请求，停止扫描")
            break
        size = min(BATCH_SIZE, target_size - len(all_items))
        post_data = {"page": page, "page_size": size, "keyword": keyword_base64}
        try:
            await asyncio.sleep(DAYDAYMAP_API_DELAY * 0.5)
            async with session.post(
                "https://www.daydaymap.com/api/v1/raymap/search/all",
                headers=headers, json=post_data,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("code") == 200:
                        inner = data.get("data", {})
                        items = inner.get("list", [])
                        if not items:
                            break
                        _stats_add(stats, 'api_items', len(items))
                        logger.info(f"[DayDayMap] 第{page}页，{len(items)} 条")
                        for item in items:
                            ip = item.get("ip")
                            if ip:
                                try:
                                    port = int(item.get("port", 8080))
                                except (TypeError, ValueError):
                                    port = 8080  # 脏数据跳过端口转换，用默认值而非中断分页
                                all_items.append({
                                    "ip": ip, "port": port,
                                    "province": (item.get("province", "") or (item.get("location", {}) or {}).get("province_cn", "")),
                                    "city": (item.get("city", "") or (item.get("location", {}) or {}).get("city_cn", ""))
                                })
                        _stats_set(stats, 'probed_hosts', len(all_items))
                        if len(items) < size:
                            break
                        page += 1
                    else:
                        logger.warning(f"[DayDayMap] API 返回错误: {data.get('message')}")
                        break
                elif resp.status == 403:
                    raise KeyDepletedError("DayDayMap key 积分耗尽")
                else:
                    logger.warning(f"[DayDayMap] 请求失败 HTTP {resp.status}")
                    break
        except KeyDepletedError:
            raise  # 让 key 耗尽冒泡到 _run_with_key_rotation 触发轮换
        except asyncio.TimeoutError:
            logger.warning(f"[DayDayMap] 第{page}页超时")
            break
        except Exception as e:
            logger.warning(f"[DayDayMap] 批次 {page} 失败: {e}")
            break
    if not all_items:
        return []
    logger.info(f"[DayDayMap] 获取到 {len(all_items)} 个IP")
    all_items = all_items[:target_size]
    entries, success = [], []

    async def f(item):
        ch = await extract_channels_from_ip(item["ip"], item["port"], session, item["province"], item["city"])
        if ch:
            success.append((item["ip"], item["port"]))
        return ch

    for lst in await asyncio.gather(*[f(it) for it in all_items]):
        if lst:
            entries.extend(lst)
    if config_bridge.get_scan_config().get("enable_c_scan") and success:
        c_entries = await smart_c_segment_scan(success, session)
        _stats_add(stats, 'c_segment_channels', len(c_entries))
        entries.extend(c_entries)
    _stats_set(stats, 'extracted_channels', len(entries))
    return entries

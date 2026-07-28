# -*- coding: utf-8 -*-
"""JSMpeg Streamer 扫描模块。"""

import asyncio
import base64
from datetime import datetime, timedelta

import aiohttp

from .. import config_bridge
from ..network import get_session
from ..logger_bridge import logger
from .shared import KeyDepletedError, _is_stop_requested, normalize_cctv_name, classify_channel_full


async def jsmpeg_streamer_scan(province=None, operator=None, size=30, session=None):
    logger.info(f"[JSMpeg] 开始扫描, province={province}, operator={operator}, size={size}")
    if session is None:
        session = get_session(limit=30, force_close=True)
    quake_key = config_bridge.get_scan_config().get("quake_key")
    hunter_key = config_bridge.get_scan_config().get("hunter_key")
    ddm_key = config_bridge.get_scan_config().get("daydaymap_api_key")

    collected_ips = {}  # (ip, port) -> 来源平台名（Quake/Hunter/DayDayMap）

    one_month_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    base_query = 'body="jsmpeg-streamer"'
    op_cond = f' AND isp="{operator}"' if operator else ''
    hunter_prov_cond = f' && ip.province=="{province}"' if province else ''
    ddm_prov_cond = f' && province=="{province}"' if province else ''
    quake_prov_cond = f' AND province="{province}"' if province else ''

    hunter_time_cond = f' && after="{one_month_ago}"'
    # 注意：Quake 不再使用 after 条件，避免高级会员限制

    if quake_key:
        try:
            # 去掉 after 时间条件
            query = f'{base_query}{quake_prov_cond}{op_cond}'
            logger.info(f"[JSMpeg] Quake 查询语句: {query}")
            async with session.post(
                "https://quake.360.net/api/v3/search/quake_service",
                headers={"X-QuakeToken": quake_key, "Content-Type": "application/json"},
                json={"query": query, "start": 0, "size": size, "latest": True},
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status == 200:
                    j = await resp.json()
                    if j.get("code") == 0:
                        items = j.get("data", [])
                        for item in items:
                            ip = item.get("ip")
                            port = item.get("port", 8080)
                            if ip and (ip, port) not in collected_ips:
                                collected_ips[(ip, port)] = 'Quake 360'
                        logger.info(f"[JSMpeg] Quake 发现 {len(items)} 个IP")
                    else:
                        logger.warning(f"[JSMpeg] Quake 返回错误: {j.get('message')}")
        except Exception as e:
            logger.warning(f"[JSMpeg] Quake 查询失败: {e}")

    if hunter_key and len(collected_ips) < size:
        try:
            query = f'web.body="jsmpeg-streamer"{hunter_prov_cond}{hunter_time_cond}{op_cond}'
            logger.info(f"[JSMpeg] Hunter 查询语句: {query}")
            qb = base64.urlsafe_b64encode(query.encode()).decode().rstrip('=')
            hunter_page_size = min(10, size)
            async with session.get(
                "https://hunter.qianxin.com/openApi/search",
                params={"api-key": hunter_key, "search": qb, "page": 1, "page_size": hunter_page_size, "is_web": 1},
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status == 200:
                    j = await resp.json()
                    if j.get("code") in (200, 0):
                        data = j.get("data")
                        if data is None:
                            items = []
                        else:
                            items = data.get("arr", [])
                        for item in items:
                            ip = item.get("ip")
                            port = item.get("port", 8080)
                            if ip and (ip, port) not in collected_ips:
                                collected_ips[(ip, port)] = 'Hunter'
                        logger.info(f"[JSMpeg] Hunter 发现 {len(items)} 个IP")
                    else:
                        logger.warning(f"[JSMpeg] Hunter 返回错误: {j.get('message')}")
                elif resp.status == 403:
                    raise KeyDepletedError("Hunter key 积分耗尽")
                else:
                    logger.warning(f"[JSMpeg] Hunter HTTP {resp.status}")
        except KeyDepletedError:
            raise
        except Exception as e:
            logger.warning(f"[JSMpeg] Hunter 查询失败: {e}")

    if ddm_key and len(collected_ips) < size:
        try:
            query = f'body="jsmpeg-streamer"{ddm_prov_cond}{op_cond}'
            logger.info(f"[JSMpeg] DayDayMap 查询语句: {query}")
            keyword_base64 = base64.b64encode(query.encode()).decode()
            async with session.post(
                "https://www.daydaymap.com/api/v1/raymap/search/all",
                headers={"api-key": ddm_key, "Content-Type": "application/json"},
                json={"page": 1, "page_size": min(size, 100), "keyword": keyword_base64},
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("code") == 200:
                        items = data.get("data", {}).get("list", [])
                        for item in items:
                            ip = item.get("ip")
                            if ip:
                                port = int(item.get("port", 8080))
                                if (ip, port) not in collected_ips:
                                    collected_ips[(ip, port)] = 'DayDayMap'
                        logger.info(f"[JSMpeg] DayDayMap 发现 {len(items)} 个IP")
                    else:
                        logger.warning(f"[JSMpeg] DayDayMap 返回错误: {data.get('message')}")
                elif resp.status == 403:
                    raise KeyDepletedError("DayDayMap key 积分耗尽")
                else:
                    logger.warning(f"[JSMpeg] DayDayMap HTTP {resp.status}")
        except KeyDepletedError:
            raise
        except Exception as e:
            logger.warning(f"[JSMpeg] DayDayMap 查询失败: {e}")

    if not collected_ips:
        logger.info("[JSMpeg] 未发现服务器")
        return []

    logger.info(f"[JSMpeg] 共发现 {len(collected_ips)} 个潜在服务器，开始提取频道列表")
    entries = []
    async def process_server(ip, port, source):
        base_url = f"http://{ip}:{port}"
        list_urls = [
            f"{base_url}/streamer/list",
            f"{base_url}/list",
            f"{base_url}/api/channels",
            f"{base_url}/channels.json"
        ]
        for list_url in list_urls:
            try:
                async with session.get(list_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                    if not isinstance(data, list):
                        if isinstance(data, dict) and "channels" in data:
                            data = data["channels"]
                        else:
                            continue
                    chs = []
                    for ch_info in data:
                        key = ch_info.get("key")
                        raw_name = ch_info.get("name")
                        if not key or not raw_name:
                            continue
                        stream_url = f"{base_url}/hls/{key}/index.m3u8"
                        norm_name = normalize_cctv_name(raw_name)
                        resolved_name, cat, final_prov, final_city = classify_channel_full(norm_name, province)
                        if resolved_name is None:
                            continue
                        chs.append({
                            'name': resolved_name,
                            'url': stream_url,
                            'category': cat,
                            'province': final_prov,
                            'city': final_city,
                            'ip_province': province or '',
                            'name_province': final_prov if final_prov != '未知' else None,
                            'source_ip': ip,
                            'scan_source': source
                        })
                    if chs:
                        logger.debug(f"[JSMpeg] 从 {ip}:{port} 的 {list_url} 提取到 {len(chs)} 个频道")
                        return chs
            except Exception as e:
                logger.debug(f"[JSMpeg] 尝试 {list_url} 失败: {e}")
                continue
        return []

    tasks = [process_server(ip, port, source) for (ip, port), source in collected_ips.items()]
    for result in await asyncio.gather(*tasks, return_exceptions=True):
        if _is_stop_requested():
            logger.info("[JSMpeg] 检测到中止请求，停止扫描")
            break
        if isinstance(result, list) and result:
            entries.extend(result)
    logger.info(f"[JSMpeg] 扫描完成，提取到 {len(entries)} 个频道")
    return entries

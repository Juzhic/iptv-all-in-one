# -*- coding: utf-8 -*-
"""IPTV 互动电视系统扫描模块。"""

import asyncio
import base64
import re
from urllib.parse import urljoin

import aiohttp

from . import config_bridge
from .config_bridge import API_REQUEST_DELAY
from .network import get_session
from .logger_bridge import logger
from .shared import KeyDepletedError, _is_stop_requested


async def iptv_interactive_scan(api_key, query=None, target_size=30, session=None):
    if not api_key:
        logger.warning("[IPTV互动] 未配置 Hunter API Key，跳过")
        return []
    if session is None:
        session = get_session(limit=30, force_close=True)
    if query is None:
        query = 'title:"首页 - IPTV互动电视系统"'

    collected_entries = []
    all_ips = []
    page = 1
    page_size = 50
    max_pages = 5
    while len(all_ips) < target_size and page <= max_pages:
        try:
            await asyncio.sleep(API_REQUEST_DELAY * 0.5)
            qb = base64.urlsafe_b64encode(query.encode()).decode().rstrip('=')
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
                        logger.info(f"[IPTV互动] 第{page}页，{len(items)} 个IP")
                        for item in items:
                            ip = item.get("ip")
                            port = item.get("port", 8080)
                            if ip:
                                all_ips.append((ip, port))
                        if len(items) < page_size:
                            break
                        page += 1
                    else:
                        logger.warning(f"[IPTV互动] API 错误: {j.get('message')}")
                        break
                elif r.status == 403:
                    raise KeyDepletedError("[IPTV互动] Hunter API Key 无效或积分耗尽")
                else:
                    logger.warning(f"[IPTV互动] HTTP {r.status}")
                    break
        except KeyDepletedError:
            raise
        except asyncio.TimeoutError:
            logger.warning("[IPTV互动] 请求超时")
            break
        except Exception as e:
            logger.warning(f"[IPTV互动] 扫描失败: {e}")
            break

    if not all_ips:
        return []

    logger.info(f"[IPTV互动] 共发现 {len(all_ips)} 个IP，开始并发提取（超时8秒，并发15）")
    sem = asyncio.Semaphore(15)
    async def fetch_one(ip, port):
        async with sem:
            try:
                chs = await asyncio.wait_for(extract_iptv_interactive_channels(ip, port, session), timeout=8)
                return chs
            except asyncio.TimeoutError:
                logger.debug(f"[IPTV互动] {ip}:{port} 超时")
                return []
            except Exception as e:
                logger.debug(f"[IPTV互动] {ip}:{port} 失败: {e}")
                return []
    tasks = [fetch_one(ip, port) for ip, port in all_ips[:target_size]]
    results = await asyncio.gather(*tasks)
    for chs in results:
        if _is_stop_requested():
            logger.info("[IPTV互动] 检测到中止请求，停止扫描")
            break
        collected_entries.extend(chs)
    logger.info(f"[IPTV互动] 共提取 {len(collected_entries)} 个频道")
    return collected_entries


async def extract_iptv_interactive_channels(ip, port, session):
    base_url = f"http://{ip}:{port}"

    # 快速预检
    try:
        async with session.get(base_url, timeout=aiohttp.ClientTimeout(total=3)) as resp:
            if resp.status != 200:
                return []
            text = await resp.text()
            if "IPTV互动电视系统" not in text and "互动电视" not in text:
                return []
    except Exception:
        return []

    channels = []

    # 1. 常见 JSON 接口
    json_endpoints = [
        "/api/channels",
        "/channels",
        "/iptv/live/1000.json",
        "/live/channels.json",
        "/api/live/channels"
    ]
    for endpoint in json_endpoints:
        try:
            url = urljoin(base_url, endpoint)
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if isinstance(data, list):
                        channel_list = data
                    elif isinstance(data, dict):
                        channel_list = data.get("data") or data.get("channels") or []
                    else:
                        continue
                    if channel_list:
                        for ch in channel_list:
                            name = ch.get("name") or ch.get("title") or ch.get("channel_name")
                            ch_id = ch.get("id") or ch.get("channel_id")
                            if not name or not ch_id:
                                continue
                            stream_url = f"{base_url}/live/{ch_id}/index.m3u8"
                            std_name, cat = resolve_iptv_interactive_channel(name)
                            channels.append({
                                'name': std_name,
                                'url': stream_url,
                                'category': cat,
                                'province': '未知',
                                'city': '',
                                'ip_province': '',
                                'name_province': None,
                                'source_ip': ip
                            })
                        if channels:
                            logger.debug(f"[IPTV互动] {ip}:{port} 从 JSON 接口提取到 {len(channels)} 个频道")
                            return channels
        except Exception:
            continue

    # 2. 枚举 /live/ 目录
    try:
        list_url = urljoin(base_url, "/live/")
        async with session.get(list_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status == 200:
                text = await resp.text()
                ids = set(re.findall(r'href="(\d+)/"', text))
                if ids:
                    logger.debug(f"[IPTV互动] {ip}:{port} 从目录发现 {len(ids)} 个节目ID")
                    for ch_id in list(ids)[:50]:
                        stream_url = f"{base_url}/live/{ch_id}/index.m3u8"
                        try:
                            async with session.head(stream_url, timeout=aiohttp.ClientTimeout(total=1.5)) as head_resp:
                                if head_resp.status != 200:
                                    continue
                        except Exception:
                            continue
                        name = f"Channel {ch_id}"
                        std_name, cat = resolve_iptv_interactive_channel(name)
                        channels.append({
                            'name': std_name,
                            'url': stream_url,
                            'category': cat,
                            'province': '未知',
                            'city': '',
                            'ip_province': '',
                            'name_province': None,
                            'source_ip': ip
                        })
                    if channels:
                        logger.debug(f"[IPTV互动] {ip}:{port} 从目录枚举提取到 {len(channels)} 个频道")
                        return channels
    except Exception:
        pass

    # 3. 兜底枚举 1-60
    logger.debug(f"[IPTV互动] {ip}:{port} 尝试兜底枚举 1-60")
    consecutive_failures = 0
    for ch_id in range(1, 61):
        stream_url = f"{base_url}/live/{ch_id}/index.m3u8"
        try:
            async with session.head(stream_url, timeout=aiohttp.ClientTimeout(total=1.5)) as resp:
                if resp.status == 200:
                    consecutive_failures = 0
                    name = f"Channel {ch_id}"
                    std_name, cat = resolve_iptv_interactive_channel(name)
                    channels.append({
                        'name': std_name,
                        'url': stream_url,
                        'category': cat,
                        'province': '未知',
                        'city': '',
                        'ip_province': '',
                        'name_province': None,
                        'source_ip': ip
                    })
                else:
                    consecutive_failures += 1
                    if consecutive_failures > 10:
                        break
        except Exception:
            consecutive_failures += 1
            if consecutive_failures > 10:
                break
    if channels:
        logger.debug(f"[IPTV互动] {ip}:{port} 从兜底枚举提取到 {len(channels)} 个频道")
    return channels


def resolve_iptv_interactive_channel(name):
    from ..channel_utils import resolve_name
    std_name, _ = resolve_name(name)
    is_cctv = std_name.startswith('CCTV') or std_name in (
        'CCTV-1','CCTV-2','CCTV-3','CCTV-4','CCTV-5','CCTV-5+','CCTV-6','CCTV-7',
        'CCTV-8','CCTV-9','CCTV-10','CCTV-11','CCTV-12','CCTV-13','CCTV-14',
        'CCTV-15','CCTV-16','CCTV-17'
    )
    if is_cctv:
        cat = '央视频道'
    else:
        cat = '港澳台频道'
    return std_name, cat

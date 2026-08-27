# -*- coding: utf-8 -*-
"""Tvheadend 扫描模块。"""

import asyncio
import base64
from urllib.parse import urljoin

import aiohttp

from .. import config_bridge
from ..config_bridge import API_REQUEST_DELAY
from ..network import get_session
from ..logger_bridge import logger
from .shared import KeyDepletedError, _is_stop_requested


async def tvheadend_scan(api_key, query=None, target_size=30, session=None):
    if not api_key:
        logger.warning("[Tvheadend] 未配置 Hunter API Key，跳过")
        return []
    if session is None:
        session = get_session(limit=30, force_close=True)
    if query is None:
        query = 'web.body="Tvheadend" && ip.province=="中国香港"'
    collected_entries = []
    all_ips = []
    page = 1
    page_size = min(10, target_size)
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
                        logger.info(f"[Tvheadend] 第{page}页，{len(items)} 个IP")
                        for item in items:
                            ip = item.get("ip")
                            port = item.get("port", 9981)
                            if ip:
                                all_ips.append((ip, port))
                        if len(items) < page_size:
                            break
                        page += 1
                    else:
                        logger.warning(f"[Tvheadend] API 错误: {j.get('message')}")
                        break
                elif r.status == 403:
                    raise KeyDepletedError("[Tvheadend] Hunter API Key 无效或积分耗尽")
                else:
                    logger.warning(f"[Tvheadend] HTTP {r.status}")
                    break
        except KeyDepletedError:
            raise
        except asyncio.TimeoutError:
            logger.warning("[Tvheadend] 请求超时")
            break
        except Exception as e:
            logger.warning(f"[Tvheadend] 扫描失败: {e}")
            break
    if not all_ips:
        return []
    logger.info(f"[Tvheadend] 共发现 {len(all_ips)} 个IP，开始并发提取（超时3秒，并发20）")
    sem = asyncio.Semaphore(20)
    async def fetch_one(ip, port):
        async with sem:
            try:
                pre_url = f"http://{ip}:{port}/playlist?profile=pass"
                try:
                    async with session.head(pre_url, timeout=aiohttp.ClientTimeout(total=2)) as head_resp:
                        if head_resp.status != 200:
                            return []
                except Exception:
                    return []
                chs = await asyncio.wait_for(extract_tvheadend_channels(ip, port, session), timeout=5)
                return chs
            except asyncio.TimeoutError:
                logger.debug(f"[Tvheadend] {ip}:{port} 超时")
                return []
            except Exception as e:
                logger.debug(f"[Tvheadend] {ip}:{port} 失败: {e}")
                return []
    tasks = [fetch_one(ip, port) for ip, port in all_ips[:target_size]]
    results = await asyncio.gather(*tasks)
    for chs in results:
        if _is_stop_requested():
            logger.info("[Tvheadend] 检测到中止请求，停止扫描")
            break
        collected_entries.extend(chs)
    logger.info(f"[Tvheadend] 共提取 {len(collected_entries)} 个频道")
    return collected_entries


async def extract_tvheadend_channels(ip, port, session):
    base_url = f"http://{ip}:{port}"
    playlist_url = f"{base_url}/playlist?profile=pass"
    try:
        async with session.get(playlist_url, timeout=aiohttp.ClientTimeout(total=3)) as resp:
            if resp.status != 200:
                return []
            text = await resp.text()
            lines = text.splitlines()
            channels = []
            current_name = None
            for line in lines:
                line = line.strip()
                if line.startswith('#EXTINF:'):
                    parts = line.split(',', 1)
                    if len(parts) == 2:
                        current_name = parts[1].strip()
                elif line and not line.startswith('#') and current_name:
                    stream_url = line
                    if not stream_url.startswith('http'):
                        stream_url = urljoin(base_url + '/', stream_url)
                    std_name, cat = resolve_tvheadend_channel(current_name)
                    ch = {
                        'name': std_name,
                        'url': stream_url,
                        'category': cat,
                        'province': '香港',
                        'city': '',
                        'ip_province': '香港',
                        'name_province': None,
                        'source_ip': ip
                    }
                    channels.append(ch)
                    current_name = None
            if channels:
                logger.debug(f"[Tvheadend] 从 {ip}:{port} 提取到 {len(channels)} 个频道")
            return channels
    except asyncio.TimeoutError:
        logger.debug(f"[Tvheadend] 提取 {ip}:{port} 超时")
        return []
    except Exception as e:
        logger.debug(f"[Tvheadend] 提取 {ip}:{port} 失败: {e}")
        return []


def resolve_tvheadend_channel(name):
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

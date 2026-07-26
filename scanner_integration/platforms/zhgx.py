# -*- coding: utf-8 -*-
"""ZHGXTV 平台扫描模块。"""

import asyncio
import base64
from urllib.parse import urljoin

import aiohttp

from . import config_bridge
from .config_bridge import API_REQUEST_DELAY
from .network import global_sem, get_session
from .logger_bridge import logger
from .shared import is_valid_stream_url, _is_stop_requested, classify_channel_full
from .ip_extract import smart_c_segment_scan


async def zhgx_scan(size=10, session=None):
    ips = set()
    quake_key = config_bridge.get_scan_config().get("quake_key")
    if quake_key:
        await asyncio.sleep(API_REQUEST_DELAY)
        try:
            if session is None: session = get_session(limit=30, force_close=True)
            async with session.post(
                "https://quake.360.net/api/v3/search/quake_service",
                headers={"X-QuakeToken": quake_key, "Content-Type": "application/json"},
                json={"query": 'body="ZHGXTV"', "start": 0, "size": size, "latest": True},
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status == 200:
                    j = await resp.json()
                    if j.get("code") == 0:
                        for item in j.get("data", []):
                            ip = item.get("ip"); port = item.get("port", 80)
                            if ip: ips.add((ip, port))
        except Exception as e:
            logger.debug(f"[ZHGX] Quake 查询失败: {e}")
    hunter_key = config_bridge.get_scan_config().get("hunter_key")
    if hunter_key:
        await asyncio.sleep(API_REQUEST_DELAY)
        try:
            qb = base64.urlsafe_b64encode('web.body="ZHGXTV"'.encode()).decode().rstrip('=')
            if session is None: session = get_session(limit=30, force_close=True)
            async with session.get(
                "https://hunter.qianxin.com/openApi/search",
                params={"api-key": hunter_key, "search": qb, "page": 1, "page_size": min(10, size), "is_web": 1},
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status == 200:
                    j = await resp.json()
                    if j.get("code") in (200, 0):
                        for item in j.get("data", {}).get("arr", []):
                            ip = item.get("ip"); port = item.get("port", 80)
                            if ip: ips.add((ip, port))
        except Exception as e:
            logger.debug(f"[ZHGX] Hunter 查询失败: {e}")
    if not ips:
        logger.info("[ZHGX] 未发现IP")
        return []
    logger.info(f"[ZHGX] {len(ips)} IP")
    entries, success = [], []
    if session is None:
        session = get_session(limit=30, force_close=True)
    async def f(ip, port):
        base = f"http://{ip}:{port}"
        async with global_sem:
            try:
                async with session.get(f"{base}/ZHGXTV/Public/json/live_interface.txt", timeout=aiohttp.ClientTimeout(5)) as r:
                    if r.status == 200:
                        text = await r.text()
                        chs = []
                        for line in text.splitlines():
                            line = line.strip()
                            if not line or ',' not in line: continue
                            parts = line.split(',', 1)
                            if len(parts) < 2: continue
                            name, url_part = parts[0].strip(), parts[1].strip()
                            if not name or not url_part: continue
                            if url_part.startswith('http://') or url_part.startswith('https://'):
                                full = url_part
                            else:
                                full = url_part if url_part.startswith('http') else urljoin(base + '/', url_part)
                            if not is_valid_stream_url(full):
                                continue
                            resolved, cat, final_prov, final_city = classify_channel_full(name)
                            if resolved is None:
                                continue
                            chs.append({
                                'name': resolved, 'url': full, 'category': cat,
                                'province': final_prov,
                                'city': final_city,
                                'ip_province': final_prov,
                                'name_province': final_prov if final_prov != '未知' else None,
                                'source_ip': ip
                            })
                        if chs: success.append((ip, port))
                        return chs
            except Exception as e:
                logger.debug(f"[ZHGX] {ip}:{port} 失败: {e}")
        return []
    for lst in await asyncio.gather(*[f(ip, port) for ip, port in ips]):
        if _is_stop_requested():
            logger.info("[ZHGX] 检测到中止请求，停止扫描")
            break
        if lst: entries.extend(lst)
    if config_bridge.get_scan_config().get("enable_c_scan") and success:
        entries.extend(await smart_c_segment_scan(success, session))
    return entries

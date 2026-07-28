# -*- coding: utf-8 -*-
"""DuckDuckGo 搜索扫描模块。"""

import asyncio
import socket
from urllib.parse import urlparse

from .. import config_bridge
from ..network import get_session
from ..logger_bridge import logger
from .shared import _is_stop_requested
from .ip_extract import extract_channels_from_ip, smart_c_segment_scan

_DDGS_CLASS = None
_DDGS_IMPORT_ATTEMPTED = False


def _get_ddgs_class():
    global _DDGS_CLASS, _DDGS_IMPORT_ATTEMPTED
    if not _DDGS_IMPORT_ATTEMPTED:
        _DDGS_IMPORT_ATTEMPTED = True
        try:
            from ddgs import DDGS as ddgs_class
            _DDGS_CLASS = ddgs_class
        except ImportError:
            _DDGS_CLASS = None
    return _DDGS_CLASS


async def ddgs_scan(query=None, target_size=30, session=None):
    ddgs_class = _get_ddgs_class()
    if ddgs_class is None:
        logger.warning("[DDGS] ddgs 库未安装，跳过扫描")
        return []
    if session is None:
        session = get_session(limit=30, force_close=True)
    if not query:
        query = '("iptv/live/zh_cn.js" OR "streamer/list" OR "1000.json") AND (hotel OR iptv)'
    try:
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(
            None, lambda: list(ddgs_class().text(query, max_results=target_size))
        )
        if not results:
            logger.info("[DDGS] 未搜索到结果")
            return []
        logger.info(f"[DDGS] 获取到 {len(results)} 个结果")
        domains = set()
        for item in results:
            url = item.get("href", "")
            if not url:
                continue
            parsed = urlparse(url)
            domain = parsed.netloc
            if domain:
                domains.add(domain)
        logger.info(f"[DDGS] 获取到 {len(domains)} 个唯一域名")
        loop = asyncio.get_running_loop()
        ip_set = set()
        for domain in domains:
            try:
                ips = await loop.getaddrinfo(domain, None, family=socket.AF_INET)
                for ip_info in ips:
                    ip = ip_info[4][0]
                    ip_set.add(ip)
            except Exception as e:
                logger.debug(f"[DDGS] DNS 解析 {domain} 失败: {e}")
        logger.info(f"[DDGS] 解析出 {len(ip_set)} 个 IP")
        entries = []
        success_ips = []
        for ip in ip_set:
            if _is_stop_requested():
                logger.info("[DDGS] 检测到中止请求，停止扫描")
                break
            for port in config_bridge.get_scan_config().get(
                    'scan_ports', [8080, 80, 443, 9981, 8888, 8000, 9090, 3000, 5000, 8443]):
                ch = await extract_channels_from_ip(ip, port, session, timeout=3)
                if ch:
                    entries.extend(ch)
                    success_ips.append((ip, port))
                    break
        if config_bridge.get_scan_config().get("enable_c_scan") and success_ips:
            entries.extend(await smart_c_segment_scan(
                success_ips, session, source_key='ddgs'
            ))
        return entries
    except Exception as e:
        logger.warning(f"[DDGS] 搜索失败: {e}")
        return []

# -*- coding: utf-8 -*-
"""Fofa 平台扫描模块。"""

import asyncio
import base64

from ipaddress import ip_address

from ..fofa_api import FofaAPIError, request_fofa

from .. import config_bridge
from ..config_bridge import API_REQUEST_DELAY
from ..network import get_session
from ..logger_bridge import logger
from .shared import KeyDepletedError, _is_stop_requested, _stats_add, _stats_set
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
    if target_size is None:
        target_size = config_bridge.get_scan_config().get("fofa_size", 200)
    _stats_set(stats, 'target_size', target_size)
    if target_size <= 0 or _is_stop_requested():
        return []
    if session is None:
        async with get_session(limit=30, force_close=True) as owned_session:
            return await fofa_scan(api_key, query, target_size, owned_session, stats)
    # FOFA allows 10,000 rows/page. A normal configured target fits one request.
    # Keep size constant across pages: changing it changes the server-side offset.
    batch_size = min(10000, target_size)
    collected_entries, collected_success = [], []
    qbase64 = base64.b64encode(query.encode('utf-8')).decode('ascii')
    page = 1
    for start in range(0, target_size, batch_size):
        if _is_stop_requested():
            logger.info("[Fofa] 检测到中止请求，停止扫描")
            break
        size = batch_size
        try:
            await asyncio.sleep(API_REQUEST_DELAY * 0.5)

            if _is_stop_requested():
                break
            j = await request_fofa(
                session, 'search/all', api_key, qbase64=qbase64,
                size=size, page=page, fields='ip,port,region,city',
            )
            results = j.get('results')
            if not isinstance(results, list):
                raise FofaAPIError('FOFA 搜索结果格式异常')
            if not results:
                break
            _stats_add(stats, 'api_items', len(results))
            logger.info(f"[Fofa] 第{page}页，{len(results)} 条")
            items = []
            for row in results[:target_size - start]:
                if not isinstance(row, (list, tuple)) or len(row) < 4:
                    continue
                try:
                    ip = str(ip_address(str(row[0]).strip()))
                    port = int(row[1])
                    if not 1 <= port <= 65535:
                        continue
                except (TypeError, ValueError):
                    continue
                items.append({
                    'ip': ip, 'port': port,
                    'province': str(row[2] or ''), 'city': str(row[3] or ''),
                })

            async def extract(item):
                if _is_stop_requested():
                    return []
                _stats_add(stats, 'probed_hosts', 1)
                ch = await extract_channels_from_ip(
                    item['ip'], item['port'], session, item['province'], item['city'],
                )
                if ch:
                    collected_success.append((item['ip'], item['port']))
                return ch

            # Bound host extraction even when the API returns a large page.
            for offset in range(0, len(items), 50):
                if _is_stop_requested():
                    break
                for channels in await asyncio.gather(*[
                    extract(item) for item in items[offset:offset + 50]
                ]):
                    collected_entries.extend(channels or [])
            total = j.get('size')
            if len(results) < size or (isinstance(total, int) and page * size >= total):
                break
            page += 1
        except FofaAPIError as exc:
            logger.warning(f"[Fofa] 第{page}页失败: {exc}")
            _stats_set(stats, 'skipped_reason', str(exc))
            if exc.depleted:
                error = KeyDepletedError(str(exc))
                error.partial_entries = collected_entries
                raise error from None
            break
        except KeyDepletedError:
            raise
        except asyncio.TimeoutError:
            logger.warning(f"[Fofa] 第{page}页超时")
            break
        except Exception as e:
            logger.warning(f"[Fofa] 第{page}页失败: {type(e).__name__}")
            break
    logger.info(f"[Fofa] 总共提取频道: {len(collected_entries)}")
    if config_bridge.get_scan_config().get("enable_c_scan") and collected_success:
        c_entries = await smart_c_segment_scan(collected_success, session, stats=stats)
        _stats_add(stats, 'c_segment_channels', len(c_entries))
        collected_entries.extend(c_entries)
    _stats_set(stats, 'extracted_channels', len(collected_entries))
    return collected_entries

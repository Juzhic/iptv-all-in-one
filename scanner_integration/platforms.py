# platforms.py
import asyncio
import base64
import json
import re
import random
import time
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse
import aiohttp
import socket

from . import config_bridge
from .config_bridge import API_REQUEST_DELAY, DAYDAYMAP_API_DELAY, QUAKE_QUERY, DAYDAYMAP_QUERY
from .channel_utils import resolve_name, auto_classify, is_blacklisted, is_cctv_paid, normalize_cctv_name
from .geo_data import extract_province_from_name, CITY_TO_PROVINCE, normalize_province
from .network import global_sem, new_scan_session
from .logger_bridge import logger

# ==================== 原 scanner.py 内容 ====================
def safe_decode_json(raw):
    try:
        return json.loads(raw.decode('utf-8'))
    except:
        pass
    try:
        return json.loads(raw.decode('gbk', errors='replace'))
    except:
        return None

async def extract_channels_from_ip(ip, port, session, prov="", city="", timeout=5):
    json_urls = [
        f"http://{ip}:{port}/iptv/live/1000.json?key=txiptv",
        f"http://{ip}:{port}/iptv/live/1000.json",
        f"http://{ip}:80/iptv/live/1000.json?key=txiptv",
        f"http://{ip}:8080/iptv/live/1000.json?key=txiptv",
    ]
    async with global_sem:
        for url in json_urls[:3]:
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(timeout)) as r:
                    if r.status != 200:
                        continue
                    j = safe_decode_json(await r.read())
                    if not (isinstance(j, dict) and 'data' in j):
                        continue
                    result = []
                    for ch in j['data']:
                        if not ch.get('url'):
                            continue
                        raw_name = ch.get('name', '未知')
                        if is_blacklisted(raw_name):
                            continue
                        ch_url = ch['url']
                        full = ch_url if ch_url.startswith('http') else urljoin(f"http://{ip}:{port}/", ch_url)
                        resolved_name, cat = resolve_name(raw_name)
                        detected_prov = extract_province_from_name(resolved_name)
                        if not detected_prov and raw_name:
                            for _city_name, p in CITY_TO_PROVINCE.items():
                                if _city_name in raw_name:
                                    detected_prov = p
                                    break
                            if not detected_prov:
                                for i in range(len(raw_name)):
                                    for k in range(i+2, min(i+5, len(raw_name)+1)):
                                        sub = raw_name[i:k]
                                        if sub in CITY_TO_PROVINCE:
                                            detected_prov = CITY_TO_PROVINCE[sub]
                                            break
                                    if detected_prov:
                                        break
                        final_prov = normalize_province(detected_prov or prov)
                        cat_auto, prov_auto = auto_classify(resolved_name, cat, final_prov)
                        if cat_auto != cat or prov_auto != final_prov:
                            cat, final_prov = cat_auto, prov_auto or final_prov
                        if is_cctv_paid(resolved_name) and cat not in ('央视频道', '卫视频道', '央视付费频道'):
                            cat = '央视付费频道'
                        if cat == '地方频道':
                            if final_prov in ('香港', '澳门', '台湾'):
                                cat = '港澳台频道'
                            elif final_prov and final_prov != '未知':
                                cat = f"{final_prov}频道"
                        result.append({
                            'name': resolved_name, 'url': full, 'category': cat,
                            'province': final_prov, 'city': city,
                            'ip_province': prov, 'name_province': detected_prov,
                            'source_ip': ip
                        })
                    if result:
                        return result
            except Exception:
                continue
    return []

def get_c_segment_ips(ip):
    parts = ip.split('.')
    if len(parts) != 4:
        return []
    return [f"{'.'.join(parts[:3])}.{i}" for i in range(1, 255)]

async def c_segment_scan(base_ip, port, session, limit=50):
    all_ips = get_c_segment_ips(base_ip)
    if len(all_ips) > limit:
        base_last = int(base_ip.split('.')[-1])
        neighbors = [ip for ip in all_ips if abs(int(ip.split('.')[-1]) - base_last) <= 10]
        others = [ip for ip in all_ips if ip not in neighbors]
        scanned = neighbors + random.sample(others, min(limit - len(neighbors), len(others)))
    else:
        scanned = all_ips
    logger.info(f"[C段] {base_ip}/24 扫描 {len(scanned)} 个IP")
    entries, cnt = [], 0
    for i in range(0, len(scanned), 50):
        batch = scanned[i:i+50]
        tasks = [extract_channels_from_ip(ip, port, session, timeout=3) for ip in batch]
        for lst in await asyncio.gather(*tasks, return_exceptions=True):
            if isinstance(lst, list) and lst:
                entries.extend(lst)
                cnt += 1
        if i + 50 < len(scanned):
            await asyncio.sleep(0.5)
    logger.info(f"[C段] 完成：{cnt}个IP有数据，{len(entries)}个频道")
    return entries

# C段缓存
_c_segment_cache = {}

async def smart_c_segment_scan(successful_ips, session):
    if not config_bridge.get_scan_config().get("enable_c_scan"):
        return []
    cs_limit = config_bridge.get_scan_config().get("c_scan_limit", 50)
    max_seg = config_bridge.get_scan_config().get("c_segment_max_segments", 8)
    max_total = config_bridge.get_scan_config().get("c_segment_max_total_ips", 200)
    segs = {}
    for ip, port in successful_ips:
        seg = '.'.join(ip.split('.')[:3])
        if seg not in segs:
            segs[seg] = (ip, port)
    now = time.time()
    fresh_segs = {}
    for seg, (ip, port) in segs.items():
        last = _c_segment_cache.get(seg, 0)
        if now - last > 300:
            fresh_segs[seg] = (ip, port)
            _c_segment_cache[seg] = now
        else:
            logger.debug(f"[C段] 跳过近期已扫描的 {seg}/24")
    segs = fresh_segs
    if len(segs) > max_seg:
        segs = dict(list(segs.items())[:max_seg])
    all_ip = []
    for ip, port in segs.values():
        ips = get_c_segment_ips(ip)
        if len(ips) > cs_limit:
            bl = int(ip.split('.')[-1])
            neighbors = [x for x in ips if abs(int(x.split('.')[-1]) - bl) <= 10]
            others = [x for x in ips if x not in neighbors]
            scanned = neighbors + random.sample(others, min(cs_limit - len(neighbors), len(others)))
        else:
            scanned = ips
        all_ip.extend((x, port) for x in scanned)
    if len(all_ip) > max_total:
        logger.info(f"[C段] 限制IP总数 {max_total}")
        all_ip = random.sample(all_ip, max_total)
    logger.info(f"[C段] 最终扫描 {len(all_ip)} 个IP")
    entries, cnt = [], 0
    for i in range(0, len(all_ip), 50):
        batch = all_ip[i:i+50]
        tasks = [extract_channels_from_ip(ip, p, session, timeout=3) for ip, p in batch]
        for lst in await asyncio.gather(*tasks, return_exceptions=True):
            if isinstance(lst, list) and lst:
                entries.extend(lst)
                cnt += 1
        if i + 50 < len(all_ip):
            await asyncio.sleep(0.5)
    seen = set()
    uniq = []
    for e in entries:
        if e['url'] not in seen:
            seen.add(e['url'])
            uniq.append(e)
    logger.info(f"[C段] 发现 {len(uniq)} 个新频道")
    return uniq

# ==================== 原 platforms.py 内容（优化后） ====================
PLATFORM_TIMEOUT = 180

async def quake_scan(api_key=None, query=None, target_size=None, session=None):
    if api_key is None: api_key = config_bridge.get_scan_config().get("quake_key", "")
    if not api_key:
        logger.warning("[Quake] 未配置 API Key，跳过")
        return []
    if query is None:
        logger.warning("[Quake] 未提供搜索查询条件，跳过")
        return []
    if target_size is None: target_size = config_bridge.get_scan_config().get("quake_size", 200)
    if session is None: session = new_scan_session()
    BATCH_SIZE = 50
    collected_entries, collected_success = [], []
    for start in range(0, target_size, BATCH_SIZE):
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
                        if not items: break
                        logger.info(f"[Quake] 获取 {start}~{start+len(items)} 条")
                        async def f(item):
                            ch = await extract_channels_from_ip(
                                item.get("ip"), item.get("port", 8080), session,
                                (item.get("province", "") or (item.get("location", {}) or {}).get("province_cn", "")), (item.get("city", "") or (item.get("location", {}) or {}).get("city_cn", ""))
                            )
                            if ch:
                                collected_success.append((item.get("ip"), item.get("port", 8080)))
                            return ch
                        for lst in await asyncio.gather(*[f(it) for it in items]):
                            if lst: collected_entries.extend(lst)
                        if len(items) < size: break
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
        collected_entries.extend(await smart_c_segment_scan(collected_success, session))
    return collected_entries

async def hunter_scan(api_key, query, target_size, session=None):
    if not api_key:
        logger.warning("[Hunter] 未配置 API Key，跳过")
        return []
    if session is None:
        session = new_scan_session()
    if target_size is None:
        target_size = config_bridge.get_scan_config().get("quake_size", 200)
    MAX_PAGE_SIZE = 10
    target_size = min(target_size, 100)
    collected_entries = []
    collected_success = []
    page = 1
    BATCH_SIZE = MAX_PAGE_SIZE
    while len(collected_entries) < target_size:
        remaining = target_size - len(collected_entries)
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
                        logger.info(f"[Hunter] 第{page}页，{len(items)} 条")
                        async def f(item):
                            ch = await extract_channels_from_ip(
                                item.get("ip"), item.get("port", 8080), session,
                                (item.get("province", "") or (item.get("location", {}) or {}).get("province_cn", "")), (item.get("city", "") or (item.get("location", {}) or {}).get("city_cn", ""))
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
        collected_entries.extend(await smart_c_segment_scan(collected_success, session))
    return collected_entries

async def daydaymap_scan(api_key, query, target_size, session=None):
    if not api_key:
        logger.warning("[DayDayMap] 未配置 API Key，跳过")
        return []
    if session is None: session = new_scan_session()
    if target_size is None: target_size = config_bridge.get_scan_config().get("quake_size", 200)
    BATCH_SIZE = 50
    all_items = []
    headers = {"api-key": api_key, "Content-Type": "application/json"}
    keyword_base64 = base64.b64encode(query.encode()).decode()
    page, max_pages = 1, 5
    while len(all_items) < target_size and page <= max_pages:
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
                        if not items: break
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
                                    "province": (item.get("province", "") or (item.get("location", {}) or {}).get("province_cn", "")), "city": (item.get("city", "") or (item.get("location", {}) or {}).get("city_cn", ""))
                                })
                        if len(items) < size: break
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
    if not all_items: return []
    logger.info(f"[DayDayMap] 获取到 {len(all_items)} 个IP")
    all_items = all_items[:target_size]
    entries, success = [], []
    async def f(item):
        ch = await extract_channels_from_ip(item["ip"], item["port"], session, item["province"], item["city"])
        if ch: success.append((item["ip"], item["port"]))
        return ch
    for lst in await asyncio.gather(*[f(it) for it in all_items]):
        if lst: entries.extend(lst)
    if config_bridge.get_scan_config().get("enable_c_scan") and success:
        entries.extend(await smart_c_segment_scan(success, session))
    return entries

async def zhgx_scan(size=10, session=None):
    ips = set()
    quake_key = config_bridge.get_scan_config().get("quake_key")
    if quake_key:
        await asyncio.sleep(API_REQUEST_DELAY)
        try:
            if session is None: session = new_scan_session()
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
        except: pass
    hunter_key = config_bridge.get_scan_config().get("hunter_key")
    if hunter_key:
        await asyncio.sleep(API_REQUEST_DELAY)
        try:
            qb = base64.urlsafe_b64encode('web.body="ZHGXTV"'.encode()).decode().rstrip('=')
            if session is None: session = new_scan_session()
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
        except: pass
    if not ips:
        logger.info("[ZHGX] 未发现IP")
        return []
    logger.info(f"[ZHGX] {len(ips)} IP")
    entries, success = [], []
    if session is None:
        session = new_scan_session()
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
                            if not name or not url_part or is_blacklisted(name): continue
                            if url_part.startswith('http://') or url_part.startswith('https://'):
                                full = url_part
                            else:
                                full = url_part if url_part.startswith('http') else urljoin(base + '/', url_part)
                            resolved, cat = resolve_name(name)
                            detected = extract_province_from_name(resolved)
                            if not detected and name:
                                for city, prov in CITY_TO_PROVINCE.items():
                                    if city in name: detected = prov; break
                                if not detected:
                                    for i in range(len(name)):
                                        for j in range(i+2, min(i+5, len(name)+1)):
                                            sub = name[i:j]
                                            if sub in CITY_TO_PROVINCE:
                                                detected = CITY_TO_PROVINCE[sub]; break
                                        if detected: break
                            final = normalize_province(detected) if detected else None
                            cat_auto, prov_auto = auto_classify(resolved, cat, final)
                            if cat_auto != cat or prov_auto != final:
                                cat, final = cat_auto, prov_auto or final
                            if is_cctv_paid(resolved) and cat not in ('央视频道','卫视频道','央视付费频道'):
                                cat = '央视付费频道'
                            if cat == '地方频道':
                                if final in ('香港','澳门','台湾'): cat = '港澳台频道'
                                elif final and final != '未知': cat = f"{final}频道"
                            chs.append({
                                'name': resolved, 'url': full, 'category': cat,
                                'province': final or '',
                                'city': '',
                                'ip_province': final or '',
                                'name_province': detected,
                                'source_ip': ip
                            })
                        if chs: success.append((ip, port))
                        return chs
            except: pass
        return []
    for lst in await asyncio.gather(*[f(ip, port) for ip, port in ips]):
        if lst: entries.extend(lst)
    if config_bridge.get_scan_config().get("enable_c_scan") and success:
        entries.extend(await smart_c_segment_scan(success, session))
    return entries

# 修正后的 JSMpeg 扫描函数（全国、最近一个月）
async def jsmpeg_streamer_scan(province=None, operator=None, size=30, session=None):
    logger.info(f"[JSMpeg] 开始扫描, province={province}, operator={operator}, size={size}")
    if session is None:
        session = new_scan_session()
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
                        resolved_name, cat = resolve_name(norm_name)
                        detected_prov = extract_province_from_name(resolved_name)
                        if not detected_prov and raw_name:
                            for _city_name, p in CITY_TO_PROVINCE.items():
                                if _city_name in raw_name:
                                    detected_prov = p
                                    break
                            if not detected_prov:
                                for i in range(len(raw_name)):
                                    for k in range(i+2, min(i+5, len(raw_name)+1)):
                                        sub = raw_name[i:k]
                                        if sub in CITY_TO_PROVINCE:
                                            detected_prov = CITY_TO_PROVINCE[sub]
                                            break
                                    if detected_prov:
                                        break
                        final_prov = normalize_province(detected_prov or province)
                        cat_auto, prov_auto = auto_classify(resolved_name, cat, final_prov)
                        if cat_auto != cat or prov_auto != final_prov:
                            cat, final_prov = cat_auto, prov_auto or final_prov
                        if is_cctv_paid(resolved_name) and cat not in ('央视频道', '卫视频道', '央视付费频道'):
                            cat = '央视付费频道'
                        if cat == '地方频道':
                            if final_prov in ('香港', '澳门', '台湾'):
                                cat = '港澳台频道'
                            elif final_prov and final_prov != '未知':
                                cat = f"{final_prov}频道"
                        chs.append({
                            'name': resolved_name,
                            'url': stream_url,
                            'category': cat,
                            'province': final_prov or '',
                            'city': '',
                            'ip_province': province or '',
                            'name_province': detected_prov,
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
        if isinstance(result, list) and result:
            entries.extend(result)
    logger.info(f"[JSMpeg] 扫描完成，提取到 {len(entries)} 个频道")
    return entries

# DuckDuckGo 搜索
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
        session = new_scan_session()
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
            except:
                pass
        logger.info(f"[DDGS] 解析出 {len(ip_set)} 个 IP")
        entries = []
        success_ips = []
        for ip in ip_set:
            for port in [8080, 80, 443]:
                ch = await extract_channels_from_ip(ip, port, session, timeout=3)
                if ch:
                    entries.extend(ch)
                    success_ips.append((ip, port))
                    break
        if config_bridge.get_scan_config().get("enable_c_scan") and success_ips:
            entries.extend(await smart_c_segment_scan(success_ips, session))
        return entries
    except Exception as e:
        logger.warning(f"[DDGS] 搜索失败: {e}")
        return []

# Tvheadend 扫描（优化版）
async def tvheadend_scan(api_key, query=None, target_size=30, session=None):
    if not api_key:
        logger.warning("[Tvheadend] 未配置 Hunter API Key，跳过")
        return []
    if session is None:
        session = new_scan_session()
    if query is None:
        query = 'web.body="Tvheadend" && ip.province=="中国香港"'
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
                    logger.warning("[Tvheadend] Hunter API Key 无效或积分耗尽")
                    break
                else:
                    logger.warning(f"[Tvheadend] HTTP {r.status}")
                    break
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
                except:
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
    from .channel_utils import resolve_name
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

# IPTV互动电视系统扫描（修复版）
async def iptv_interactive_scan(api_key, query=None, target_size=30, session=None):
    if not api_key:
        logger.warning("[IPTV互动] 未配置 Hunter API Key，跳过")
        return []
    if session is None:
        session = new_scan_session()
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
                    logger.warning("[IPTV互动] Hunter API Key 无效或积分耗尽")
                    break
                else:
                    logger.warning(f"[IPTV互动] HTTP {r.status}")
                    break
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
    except:
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
                        except:
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
    for ch_id in range(1, 61):
        stream_url = f"{base_url}/live/{ch_id}/index.m3u8"
        try:
            async with session.head(stream_url, timeout=aiohttp.ClientTimeout(total=1.5)) as resp:
                if resp.status == 200:
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
                    if len(channels) == 0 and ch_id > 10:
                        break
        except:
            continue
    if channels:
        logger.debug(f"[IPTV互动] {ip}:{port} 从兜底枚举提取到 {len(channels)} 个频道")
    return channels

def resolve_iptv_interactive_channel(name):
    from .channel_utils import resolve_name
    std_name, _ = resolve_name(name)
    is_cctv = std_name.startswith('CCTV') or std_name in (
        'CCTV-1','CCTV-2','CCTV-3','CCTV-4','CCTV-5','CCTV-5+','CCTV-6','CCTV-7',
        'CCTV-8','CCTV-9','CCTV-10','CCTV-11','CCTV-12','CCTV-13','CCTV-14',
        'CCTV-15','CCTV-16','CCTV-17'
    ) or '央视' in std_name
    if is_cctv:
        cat = '央视频道'
    else:
        cat = '港澳台频道'
    return std_name, cat

# ---------- 辅助函数 ----------
def remove_duplicate_national_channels(channels):
    nat_names = {c['name'] for c in channels if c.get('category') in ('央视频道','央视付费频道','卫视频道')}
    return [c for c in channels if c.get('category') in ('央视频道','央视付费频道','卫视频道') or c['name'] not in nat_names]

def clean_url(u):
    if not isinstance(u, str): return ""
    u = u.strip()
    if u.startswith(('http://', 'https://')): return u
    if u.startswith('//'): return f"http:{u}"
    return ""

def is_valid_channel_name(name):
    if not isinstance(name, str) or not name.strip(): return False
    s = name.strip()
    if '{' in s or '}' in s: return False
    if s.startswith(('{','[','<')): return False
    if re.search(r'^(data|javascript|vbscript):', s, re.I): return False
    lowered = s.lower()
    if any(kw in lowered for kw in ['data:text/plain', 'base64,', '"status":', 'null', 'undefined', 'session']): return False
    if any(k in lowered for k in ['api_request','metrics','prometheus','method=','status=']): return False
    if '::' in s or re.search(r'\.[A-Z]', s): return False
    if re.match(r'^[a-zA-Z0-9 _\-.]+$', s) and (len(s)<4 or len(s)>20): return False
    return len(s) <= 60

def deduplicate(sources):
    seen, uniq = set(), []
    for s in sources:
        if s['url'] not in seen: seen.add(s['url']); uniq.append(s)
    return uniq

# ---------- Key 轮换辅助 ----------
class KeyDepletedError(Exception):
    """当前 key 积分耗尽。"""
    pass


async def _run_with_key_rotation(platform, scan_func, *args, session=None, **kwargs):
    """
    用 KeyManager 轮换 key 执行扫描函数。
    scan_func 的第一个参数必须是 api_key。
    403 时自动切换下一个 key 重试。
    """
    from .key_manager import KeyManager
    km = KeyManager.instance()
    keys = km.get_all_keys(platform)
    if not keys:
        return []

    last_error = None
    for key in keys:
        try:
            result = await scan_func(key, *args, session=session, **kwargs)
            return result
        except KeyDepletedError:
            km.mark_depleted(platform, key)
            continue
        except Exception as e:
            last_error = e
            break

    if last_error:
        logger.warning(f"[{platform}] 扫描异常: {last_error}")
    return []


# ---------- 主收集函数（串行化平台，JSMpeg 全国扫描一次） ----------
async def collect_all(size=None, log_fn=None):
    """采集所有平台的 IPTV 频道。
    返回 (clean_channels, actual_platforms) 元组。
    log_fn: 可选的日志回调函数，用于将进度写入前端扫描日志。"""
    def _log(msg):
        logger.info(msg)
        if log_fn:
            log_fn(msg)
    from .key_manager import KeyManager
    km = KeyManager.instance()

    quake_key = km.get_key('quake')
    hunter_key = km.get_key('hunter')
    ddm_key = km.get_key('daydaymap')
    ddgs_enabled = config_bridge.get_scan_config().get("ddgs_enabled", False)

    enabled_platforms = config_bridge.get_scan_config().get("enabled_platforms", [])
    if not enabled_platforms:
        enabled_platforms = []
        if km.get_all_keys('quake'): enabled_platforms.append("quake")
        if km.get_all_keys('hunter'): enabled_platforms.append("hunter")
        if km.get_all_keys('daydaymap'): enabled_platforms.append("daydaymap")

    target_size = size or config_bridge.get_scan_config().get("quake_size", 200)
    selected_provs = config_bridge.get_scan_config().get("selected_provinces", []) or [config_bridge.get_scan_config().get("province", "") or ""]
    operator = config_bridge.get_scan_config().get("operator", "")

    _log(f"[采集] 启用平台: {enabled_platforms}，省份数: {len(selected_provs)}")

    if not enabled_platforms and not ddgs_enabled and not km.get_all_keys('hunter'):
        _log("[采集] 未启用任何平台且无 Hunter Key，请检查配置")
        return [], []

    all_raw = []
    async with new_scan_session() as scan_session:
        for prov_idx, prov in enumerate(selected_provs, 1):
            if len(selected_provs) > 1:
                _log(f"[采集] === 省份 ({prov_idx}/{len(selected_provs)}): {prov or '全国'} ===")
            qq = QUAKE_QUERY
            hq = 'web.body="/iptv/live/zh_cn.js"'
            ddm_q = DAYDAYMAP_QUERY
            if operator:
                qq += f' AND isp="{operator}"'
                hq += f' AND isp="{operator}"'
                ddm_q += f' && isp="{operator}"'
            if prov:
                qq += f' AND province="{prov}"'
                hq += f' AND province="{prov}"'
                ddm_q += f' && province="{prov}"'

            # 串行执行每个平台（带 key 轮换）
            if "quake" in enabled_platforms and quake_key:
                _log(f"[采集] ({len(all_raw)}条) 开始扫描 Quake 360...")
                q_res = await _run_with_key_rotation('quake', quake_scan, qq, target_size, session=scan_session)
                for ch in q_res:
                    ch['platform'] = 'Quake 360'
                all_raw.extend(q_res)
                _log(f"[采集] Quake 360 完成，获得 {len(q_res)} 个频道，累计 {len(all_raw)} 条")
                await asyncio.sleep(API_REQUEST_DELAY)

            if "hunter" in enabled_platforms and hunter_key:
                _log(f"[采集] ({len(all_raw)}条) 开始扫描 Hunter...")
                h_res = await _run_with_key_rotation('hunter', hunter_scan, hq, target_size, session=scan_session)
                for ch in h_res:
                    ch['platform'] = 'Hunter'
                all_raw.extend(h_res)
                _log(f"[采集] Hunter 完成，获得 {len(h_res)} 个频道，累计 {len(all_raw)} 条")
                await asyncio.sleep(API_REQUEST_DELAY)

            if "daydaymap" in enabled_platforms and ddm_key:
                _log(f"[采集] ({len(all_raw)}条) 开始扫描 DayDayMap...")
                d_res = await _run_with_key_rotation('daydaymap', daydaymap_scan, ddm_q, target_size, session=scan_session)
                for ch in d_res:
                    ch['platform'] = 'DayDayMap'
                all_raw.extend(d_res)
                _log(f"[采集] DayDayMap 完成，获得 {len(d_res)} 个频道，累计 {len(all_raw)} 条")
                await asyncio.sleep(API_REQUEST_DELAY)

        # 其他独立扫描（ZHGX, JSMpeg, Tvheadend, IPTV互动等）
        if enabled_platforms:
            _log(f"[采集] ({len(all_raw)}条) 开始扫描 ZHGX...")
            try:
                zhgx_result = await asyncio.wait_for(zhgx_scan(target_size, session=scan_session), timeout=PLATFORM_TIMEOUT)
                for ch in zhgx_result:
                    ch['platform'] = 'ZHGX'
                all_raw.extend(zhgx_result)
                _log(f"[采集] ZHGX 完成，获得 {len(zhgx_result)} 个频道，累计 {len(all_raw)} 条")
            except asyncio.TimeoutError:
                _log("[采集] ZHGX 总超时，放弃")

        # JSMpeg 全国扫描（只执行一次，不限省份）
        _log(f"[采集] ({len(all_raw)}条) 开始扫描 JSMpeg Streamer...")
        try:
            jsmpeg_result = await asyncio.wait_for(
                jsmpeg_streamer_scan(province=None, operator=operator if operator else None, size=target_size, session=scan_session),
                timeout=PLATFORM_TIMEOUT
            )
            for ch in jsmpeg_result:
                ch['platform'] = ch.pop('scan_source', 'Quake 360')
            all_raw.extend(jsmpeg_result)
            _log(f"[采集] JSMpeg 完成，获得 {len(jsmpeg_result)} 个频道，累计 {len(all_raw)} 条")
        except asyncio.TimeoutError:
            _log("[采集] JSMpeg 全国扫描总超时，放弃")

        if hunter_key:
            _log(f"[采集] ({len(all_raw)}条) 开始扫描 Tvheadend...")
            try:
                tvh_result = await asyncio.wait_for(tvheadend_scan(hunter_key, None, 30, session=scan_session), timeout=PLATFORM_TIMEOUT)
                for ch in tvh_result:
                    ch['platform'] = 'Tvheadend'
                all_raw.extend(tvh_result)
                _log(f"[采集] Tvheadend 完成，获得 {len(tvh_result)} 个频道，累计 {len(all_raw)} 条")
            except asyncio.TimeoutError:
                _log("[采集] Tvheadend 总超时，放弃")

        if hunter_key:
            _log(f"[采集] ({len(all_raw)}条) 开始扫描 IPTV互动...")
            try:
                iptv_interactive_result = await asyncio.wait_for(iptv_interactive_scan(hunter_key, None, 30, session=scan_session), timeout=PLATFORM_TIMEOUT)
                for ch in iptv_interactive_result:
                    ch['platform'] = 'IPTV互动'
                all_raw.extend(iptv_interactive_result)
                _log(f"[采集] IPTV互动 完成，获得 {len(iptv_interactive_result)} 个频道，累计 {len(all_raw)} 条")
            except asyncio.TimeoutError:
                _log("[采集] IPTV互动 总超时，放弃")

        if ddgs_enabled:
            _log(f"[采集] ({len(all_raw)}条) 开始扫描 DDGS...")
            try:
                ddgs_result = await asyncio.wait_for(ddgs_scan(None, target_size, session=scan_session), timeout=PLATFORM_TIMEOUT)
                for ch in ddgs_result:
                    ch['platform'] = 'DDGS'
                all_raw.extend(ddgs_result)
                _log(f"[采集] DDGS 完成，获得 {len(ddgs_result)} 个频道，累计 {len(all_raw)} 条")
            except asyncio.TimeoutError:
                _log("[采集] DDGS 总超时，放弃")

        # 域名/IP 扫描
        _log(f"[采集] ({len(all_raw)}条) 开始域名/IP扫描...")
        try:
            from .domain_ip_scanner import domain_ip_scan
            domain_entries = await domain_ip_scan(session=scan_session)
            for ent in domain_entries:
                ip = ent['ip']
                for port in [8080, 80, 443]:
                    ch = await extract_channels_from_ip(ip, port, scan_session)
                    if ch:
                        for c in ch:
                            c['platform'] = '域名/IP'
                        all_raw.extend(ch)
                        break
            _log(f"[采集] 域名/IP扫描 完成，累计 {len(all_raw)} 条")
        except Exception as e:
            _log(f"[采集] 域名/IP扫描 失败: {e}")

    clean = []
    for ent in all_raw:
        url = clean_url(ent.get('url', ''))
        if not url or not is_valid_channel_name(ent.get('name', '')) or is_blacklisted(ent['name']):
            continue
        ent['url'] = url
        ent['province'] = ent.get('province') or '未知'
        ent['ip_province'] = ent.get('ip_province') or ent.get('province', '未知')
        ent['name_province'] = ent.get('name_province')
        ent['source_ip'] = ent.get('source_ip', '')
        clean.append(ent)
    # 检测实际启用的平台（用于记录 platforms_used）
    actual_platforms = []
    if ddgs_enabled:
        actual_platforms.append('ddgs')
    if enabled_platforms:
        actual_platforms.extend(enabled_platforms)
    if km.get_all_keys('hunter'):
        if 'hunter' not in actual_platforms:
            actual_platforms.append('hunter')

    _log(f"[采集] 全部平台扫描完成，原始 {len(all_raw)} 条，清洗后 {len(clean)} 条")
    return clean, actual_platforms

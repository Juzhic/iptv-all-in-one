# domain_ip_scanner.py
import os
import re
import asyncio
import aiohttp
from typing import List, Dict, Optional
from . import config_bridge
from .logger_bridge import logger

CENSYS_API_ID = os.environ.get('CENSYS_API_ID', '')
CENSYS_API_SECRET = os.environ.get('CENSYS_API_SECRET', '')
CENSYS_BASE_URL = "https://search.censys.io/api/v1"

HOTEL_TARGET_KEYWORDS = [
    "iptv", "live", "tv", "hotel",
    "zh_cn.js", "txiptv", "ZHGXTV",
    "1000.json"
]

def is_potential_hotel_domain(domain: str) -> bool:
    domain_lower = domain.lower()
    return any(keyword in domain_lower for keyword in HOTEL_TARGET_KEYWORDS)

async def get_ip_for_domain(session: aiohttp.ClientSession, domain: str) -> List[str]:
    ips = []
    try:
        async with session.get(
            f"https://dns.google/resolve?name={domain}&type=A",
            timeout=aiohttp.ClientTimeout(total=3)
        ) as r:
            if r.status == 200:
                data = await r.json()
                ips = [ans['data'] for ans in data.get('Answer', []) if ans.get('type') == 1]
    except Exception as e:
        logger.debug(f"DNS解析 {domain} 失败: {e}")
    return ips

async def search_censys_certificates(session: aiohttp.ClientSession, query: str, max_results: int = 50) -> List[Dict]:
    if not CENSYS_API_ID or not CENSYS_API_SECRET:
        return []
    results = []
    auth = aiohttp.BasicAuth(CENSYS_API_ID, CENSYS_API_SECRET)
    try:
        async with session.post(
            f"{CENSYS_BASE_URL}/search/certificates",
            auth=auth,
            json={"query": query, "page": 1, "fields": ["parsed.names", "parsed.subject_dn"]},
            timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                results = data.get('results', [])[:max_results]
    except Exception as e:
        logger.warning(f"Censys证书搜索失败: {e}")
    return results

async def search_censys_hosts(session: aiohttp.ClientSession, query: str) -> List[Dict]:
    if not CENSYS_API_ID or not CENSYS_API_SECRET:
        return []
    results = []
    auth = aiohttp.BasicAuth(CENSYS_API_ID, CENSYS_API_SECRET)
    try:
        async with session.post(
            f"{CENSYS_BASE_URL}/search/ipv4",
            auth=auth,
            json={"query": query, "page": 1, "fields": ["ip", "protocols", "location.country", "location.province"]},
            timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                results = data.get('results', [])
    except Exception as e:
        logger.warning(f"Censys主机搜索失败: {e}")
    return results

async def enumerate_domains_from_ip(session: aiohttp.ClientSession, ip: str) -> List[str]:
    domains = []
    try:
        async with session.get(
            f"https://rapiddns.io/sameip/{ip}",
            timeout=aiohttp.ClientTimeout(total=8)
        ) as r:
            if r.status == 200:
                text = await r.text()
                domains = re.findall(r'<td>(?!\d+\.\d+\.\d+\.\d+)([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})</td>', text)
    except Exception as e:
        logger.debug(f"RapidDNS IP查询失败: {e}")
    return list(set(domains))

async def domain_ip_scan(
    target_keywords: Optional[List[str]] = None,
    max_results: int = 100,
    session: Optional[aiohttp.ClientSession] = None
) -> List[Dict]:
    all_entries = []
    if target_keywords is None:
        target_keywords = [f'body="{kw}"' for kw in HOTEL_TARGET_KEYWORDS]

    async def _scan(sess: aiohttp.ClientSession):
        entries = []
        for keyword in target_keywords:
            hosts = await search_censys_hosts(sess, keyword)
            for host in hosts:
                ip = host.get('ip')
                if ip:
                    domains = await enumerate_domains_from_ip(sess, ip)
                    for domain in domains:
                        if is_potential_hotel_domain(domain):
                            resolved_ips = await get_ip_for_domain(sess, domain)
                            for resolved_ip in resolved_ips:
                                entries.append({'ip': resolved_ip, 'domain': domain, 'source': 'rapiddns'})
        for keyword in target_keywords:
            certs = await search_censys_certificates(sess, keyword, max_results)
            for cert in certs:
                names = cert.get('parsed.names', [])
                for domain in names:
                    if is_potential_hotel_domain(domain):
                        resolved_ips = await get_ip_for_domain(sess, domain)
                        for resolved_ip in resolved_ips:
                            entries.append({'ip': resolved_ip, 'domain': domain, 'source': 'censys_cert'})
        seen = set()
        unique = []
        for e in entries:
            if e['ip'] not in seen:
                seen.add(e['ip'])
                unique.append(e)
        return unique

    if session:
        result = await _scan(session)
    else:
        async with aiohttp.ClientSession() as new_session:
            result = await _scan(new_session)

    logger.info(f"[域名/IP扫描] 共发现 {len(result)} 个唯一IP")
    return result
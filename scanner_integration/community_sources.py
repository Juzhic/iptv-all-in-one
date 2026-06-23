# -*- coding: utf-8 -*-
"""
社区 IPTV 源聚合模块。
从 GitHub 上的公开 IPTV M3U 仓库采集频道列表。
"""
import asyncio
import re

import aiohttp

from .channel_utils import classify_channel_full
from .logger_bridge import logger
from .platforms import is_valid_stream_url

# GitHub 反代前缀（国内网络无法直接访问 raw.githubusercontent.com）
# 可通过配置 github_proxy 自定义，留空则直连
GITHUB_PROXY_CANDIDATES = [
    "https://mirror.ghproxy.com/",
    "https://gh-proxy.com/",
    "https://raw.gitmirror.com/",
    "https://ghproxy.net/",
]

DEFAULT_COMMUNITY_URLS = [
    "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/cn.m3u",
    "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/hk.m3u",
    "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/tw.m3u",
    "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/mo.m3u",
    "https://raw.githubusercontent.com/suxuang/myIPTV/main/ipv4.m3u",
    "https://raw.githubusercontent.com/YueChan/Live/main/IPTV.m3u",
    "https://raw.githubusercontent.com/Guovin/TV/default/output/result.m3u",
]

_EXTINF_RE = re.compile(
    r'#EXTINF:-?\d+(?:\s+([^,]*))?,\s*(.*)',
    re.IGNORECASE,
)

_GROUP_RE = re.compile(r'group-title="([^"]*)"', re.IGNORECASE)


async def fetch_community_m3u(session, url, timeout=30):
    """下载并解析单个 M3U 文件。

    返回 list[dict]，每个 dict 包含 name, url, category, province 字段。
    """
    channels = []
    try:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=timeout),
            allow_redirects=True,
        ) as resp:
            if resp.status != 200:
                logger.warning(f"[Community] HTTP {resp.status} for {url}")
                return []
            raw = await resp.read()

        # 尝试多种编码
        text = None
        for enc in ('utf-8', 'gbk', 'gb2312', 'latin-1'):
            try:
                text = raw.decode(enc)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        if text is None:
            logger.warning(f"[Community] 无法解码 {url}")
            return []

        lines = text.splitlines()
        pending_name = None
        pending_group = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if line.startswith('#EXTINF'):
                m = _EXTINF_RE.match(line)
                if m:
                    attrs, name = m.group(1) or '', m.group(2).strip()
                    pending_name = name
                    gm = _GROUP_RE.search(attrs)
                    pending_group = gm.group(1) if gm else ''
                continue

            if line.startswith('#'):
                continue

            # 这一行应该是流 URL
            stream_url = line
            name = pending_name
            pending_name = None
            group = pending_group
            pending_group = None

            if not name or not stream_url:
                continue

            if not is_valid_stream_url(stream_url):
                continue

            # 使用 classify_channel_full 分类
            resolved, cat, prov, city = classify_channel_full(name)
            if resolved is None:
                continue

            # 如果分类为空，尝试用 group-title 补充
            if (not cat or cat == '地方频道') and group:
                cat = group

            channels.append({
                'name': resolved,
                'url': stream_url,
                'category': cat or '地方频道',
                'province': prov or '未知',
                'city': city or '',
                'platform': 'Community',
            })

        logger.info(f"[Community] {url} 解析到 {len(channels)} 个频道")

    except asyncio.TimeoutError:
        logger.warning(f"[Community] 超时: {url}")
    except aiohttp.ClientError as e:
        logger.warning(f"[Community] 网络错误 {url}: {e}")
    except Exception as e:
        logger.warning(f"[Community] 解析失败 {url}: {e}")

    return channels


async def scan_community_sources(session=None, extra_urls=None):
    """并发抓取所有社区 M3U 源，去重后返回合并列表。

    参数:
        session: 可选的 aiohttp.ClientSession，为 None 时自动创建。
        extra_urls: 可选的额外 M3U URL 列表（来自用户配置）。
    """
    from . import config_bridge

    cfg = config_bridge.get_scan_config()
    if not cfg.get('community_sources_enabled', False):
        logger.info("[Community] 社区源扫描已禁用，跳过")
        return []

    urls = list(DEFAULT_COMMUNITY_URLS)
    user_urls = cfg.get('community_source_urls', [])
    if isinstance(user_urls, list):
        urls.extend(u for u in user_urls if isinstance(u, str) and u.startswith('http'))
    if extra_urls:
        urls.extend(u for u in extra_urls if isinstance(u, str) and u.startswith('http'))

    # 去重 URL
    urls = list(dict.fromkeys(urls))

    # 应用 GitHub 反代
    github_proxy = cfg.get('github_proxy', '')
    if not github_proxy:
        # 自动探测可用的反代
        github_proxy = await _detect_github_proxy()
    if github_proxy:
        urls = [_apply_proxy(url, github_proxy) for url in urls]
        logger.info(f"[Community] 已启用 GitHub 反代: {github_proxy}")

    logger.info(f"[Community] 开始扫描 {len(urls)} 个社区源")

    own_session = session is None
    if own_session:
        from .network import get_session
        session = get_session(limit=30, timeout=60, force_close=True)

    try:
        tasks = [fetch_community_m3u(session, url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_channels = []
        for i, res in enumerate(results):
            if isinstance(res, Exception):
                logger.warning(f"[Community] {urls[i]} 异常: {res}")
                continue
            if isinstance(res, list):
                all_channels.extend(res)

        # 按 URL 去重
        seen = set()
        unique = []
        for ch in all_channels:
            url = ch.get('url', '')
            if url and url not in seen:
                seen.add(url)
                unique.append(ch)

        logger.info(f"[Community] 扫描完成，原始 {len(all_channels)} 条，去重后 {len(unique)} 条")
        return unique

    finally:
        if own_session:
            await session.close()


def _apply_proxy(url, proxy_prefix):
    """对 GitHub raw URL 应用反代前缀。"""
    if not proxy_prefix or not url.startswith('https://raw.githubusercontent.com/'):
        return url
    # 确保 proxy_prefix 以 / 结尾
    if not proxy_prefix.endswith('/'):
        proxy_prefix += '/'
    return proxy_prefix + url


async def _detect_github_proxy():
    """自动探测可用的 GitHub 反代。返回第一个可用的前缀，或空字符串。"""
    test_url = "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/cn.m3u"
    for proxy in GITHUB_PROXY_CANDIDATES:
        proxied = _apply_proxy(test_url, proxy)
        try:
            async with aiohttp.ClientSession() as s:
                async with s.head(
                    proxied,
                    timeout=aiohttp.ClientTimeout(total=8),
                    allow_redirects=True,
                ) as resp:
                    if resp.status == 200:
                        logger.info(f"[Community] 探测到可用反代: {proxy}")
                        return proxy
        except Exception:
            continue
    logger.warning("[Community] 所有反代均不可用，将直连 GitHub（可能超时）")
    return ""

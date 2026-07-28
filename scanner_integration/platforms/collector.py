# -*- coding: utf-8 -*-
"""主收集函数与 Key 轮换辅助。"""

import asyncio
import base64

from .. import config_bridge
from ..config_bridge import PLATFORM_TIMEOUT
from ..network import get_session
from ..logger_bridge import logger
from .shared import (
    QUALITY_QUERY_PROFILES, KeyDepletedError,
    _is_stop_requested, _stats_set, _yield_stat_key, _build_yield_stat,
    is_valid_channel_name,
    clean_url, remove_duplicate_national_channels, deduplicate,
)
from ..channel_utils import is_blacklisted
from .ip_extract import (
    extract_channels_from_ip, begin_c_segment_budget, end_c_segment_budget,
)
from .quake import quake_scan
from .fofa import fofa_scan
from .hunter import hunter_scan
from .daydaymap import daydaymap_scan
from .zhgx import zhgx_scan
from .jsmpeg import jsmpeg_streamer_scan
from .ddgs import ddgs_scan
from .tvheadend import tvheadend_scan
from .iptv_interactive import iptv_interactive_scan


async def _run_with_key_rotation(platform, scan_func, *args, session=None, **kwargs):
    """
    用 KeyManager 轮换 key 执行扫描函数。
    scan_func 的第一个参数必须是 api_key。
    按积分余额降序使用 key，跳过已耗尽的 key，403 时自动切换下一个 key 重试。
    """
    from ..key_manager import KeyManager, _credit_is_usable, _credit_rank
    km = KeyManager.instance()
    all_keys = km.get_all_keys(platform)
    if not all_keys:
        _stats_set(kwargs.get('stats'), 'skipped_reason', '未配置 API Key')
        return []

    credits = km.get_credits_info(platform)
    sorted_keys = sorted(all_keys, key=lambda k: _credit_rank(credits.get(k)), reverse=True)
    usable = [k for k in sorted_keys if _credit_is_usable(credits.get(k))]

    if not usable:
        logger.warning(f"[{platform}] 所有 key 积分耗尽，跳过扫描")
        _stats_set(kwargs.get('stats'), 'skipped_reason', '所有 API Key 已耗尽')
        return []

    skipped = len(all_keys) - len(usable)
    if skipped:
        logger.info(f"[{platform}] 跳过 {skipped} 个已耗尽的 key，"
                    f"剩余 {len(usable)} 个可用")

    last_error = None
    for key in usable:
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
        _stats_set(kwargs.get('stats'), 'skipped_reason', str(last_error))
    return []


# ---------- 主收集函数（串行化平台，JSMpeg 全国扫描一次） ----------
async def collect_all(size=None, log_fn=None, platforms_override=None, provinces_override=None):
    """采集所有平台的 IPTV 频道。
    返回 (clean_channels, actual_platforms) 元组。
    log_fn: 可选的日志回调函数，用于将进度写入前端扫描日志。"""
    def _log(msg):
        logger.info(msg)
        if log_fn:
            log_fn(msg)
    from ..key_manager import KeyManager
    km = KeyManager.instance()
    scan_cfg = config_bridge.get_scan_config()
    search_queries = config_bridge.build_search_queries(scan_cfg)

    quake_key = km.get_key('quake')
    hunter_key = km.get_key('hunter')
    ddm_key = km.get_key('daydaymap')
    fofa_key = km.get_key('fofa')
    ddgs_enabled = scan_cfg.get("ddgs_enabled", False)

    enabled_platforms = platforms_override if platforms_override is not None else scan_cfg.get("enabled_platforms", [])
    if isinstance(enabled_platforms, str):
        enabled_platforms = [enabled_platforms]
    enabled_platforms = [p for p in (enabled_platforms or []) if isinstance(p, str) and p]
    explicit_platforms = bool(enabled_platforms)
    if not enabled_platforms:
        available_platforms = []
        if km.get_all_keys('quake'): available_platforms.append("quake")
        if km.get_all_keys('hunter'): available_platforms.append("hunter")
        if km.get_all_keys('daydaymap'): available_platforms.append("daydaymap")
        if km.get_all_keys('fofa') and scan_cfg.get("fofa_email"): available_platforms.append("fofa")
        if scan_cfg.get("cost_saver_mode", True):
            preferred_order = ("quake", "fofa", "hunter", "daydaymap")
            enabled_platforms = [
                p for p in preferred_order
                if p in available_platforms
            ][:1]
        else:
            enabled_platforms = available_platforms

    selected_provs = provinces_override if provinces_override is not None else scan_cfg.get("selected_provinces", [])
    if isinstance(selected_provs, str):
        selected_provs = [selected_provs]
    selected_provs = [p for p in (selected_provs or []) if isinstance(p, str)]
    if not selected_provs:
        selected_provs = [scan_cfg.get("province", "") or ""]
    operator = scan_cfg.get("operator", "")

    def _target_for(platform):
        value = size if size is not None else scan_cfg.get(f"{platform}_size", scan_cfg.get("quake_size", 200))
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return 200

    def _quality_target_for(platform, profile_count=None):
        budget = scan_cfg.get("quality_query_profile_size", 120)
        try:
            budget = max(10, int(budget))
        except (TypeError, ValueError):
            budget = 120
        split_count = max(1, (profile_count or len(QUALITY_QUERY_PROFILES)) * len(selected_provs))
        per_profile = max(1, budget // split_count)
        return min(_target_for(platform), per_profile)

    def _with_filters(query, platform, prov=None):
        if not operator and not prov:
            return query
        connector = "AND" if platform == "quake" else "&&"
        filtered = f"({query})"
        if operator:
            filtered += f' {connector} isp="{operator}"'
        if prov:
            if platform == "fofa":
                filtered += f' {connector} region="{prov}"'
            elif platform == "daydaymap":
                filtered += f' {connector} province=="{prov}"'
            else:
                filtered += f' {connector} province="{prov}"'
        return filtered

    def _profile_label(platform_name, profile_label, prov):
        if prov:
            return f"{platform_name}/{profile_label}/{prov}"
        if len(selected_provs) > 1:
            return f"{platform_name}/{profile_label}/全国"
        return f"{platform_name}/{profile_label}"

    def _platform_result_log(name, stats, result_count):
        reason = stats.get('skipped_reason') if isinstance(stats, dict) else None
        if reason:
            return f"[采集] {name} 跳过：{reason}"
        api_items = stats.get('api_items', 0) if isinstance(stats, dict) else 0
        probed = stats.get('probed_hosts', api_items) if isinstance(stats, dict) else api_items
        c_count = stats.get('c_segment_channels', 0) if isinstance(stats, dict) else 0
        c_ips = stats.get('c_segment_ips', 0) if isinstance(stats, dict) else 0
        c_segments = stats.get('c_segment_segments', 0) if isinstance(stats, dict) else 0
        suffix = (
            f"，C段 {c_segments} 段/{c_ips} IP，补充 {c_count} 条"
            if c_segments or c_ips or c_count else ""
        )
        return f"[采集] {name} 完成：API命中 {api_items} 个，探测 {probed} 个，提取频道 {result_count} 条{suffix}"

    if scan_cfg.get("cost_saver_mode", True) and not explicit_platforms:
        _log(f"[采集] 省积分模式：未手动选择平台，本轮仅使用 {enabled_platforms or '无可用平台'}")
    _log(f"[采集] 启用平台: {enabled_platforms}，省份数: {len(selected_provs)}")

    if not enabled_platforms and not ddgs_enabled and not km.get_all_keys('hunter'):
        _log("[采集] 未启用任何平台且无 Hunter Key，请检查配置")
        return [], [], []

    c_segment_budget_token = begin_c_segment_budget(scan_cfg)
    all_raw = []
    yield_stats = []
    async with get_session(limit=30, force_close=True) as scan_session:
        for prov_idx, prov in enumerate(selected_provs, 1):
            if len(selected_provs) > 1:
                _log(f"[采集] === 省份 ({prov_idx}/{len(selected_provs)}): {prov or '全国'} ===")
            qq = _with_filters(search_queries["quake"], "quake", prov)
            hq = _with_filters(search_queries["hunter"], "hunter", prov)
            ddm_q = _with_filters(search_queries["daydaymap"], "daydaymap", prov)
            fofa_q = _with_filters(search_queries["fofa"], "fofa", prov)

            # 并行执行 API 平台扫描（带 key 轮换），各平台读取各自的扫描数量配置
            api_tasks = []
            if "quake" in enabled_platforms and quake_key:
                stats = {}
                target = _target_for("quake")
                stat_key = _yield_stat_key('platform', 'quake', province=prov)
                api_tasks.append((stat_key, 'Quake 360', 'quake', '', '', prov, _run_with_key_rotation('quake', quake_scan, qq, target, session=scan_session, stats=stats), stats, target))
            elif "quake" in enabled_platforms:
                _log("[采集] Quake 360 已启用但未配置 API Key，跳过")
            if "hunter" in enabled_platforms and hunter_key:
                stats = {}
                target = _target_for("hunter")
                stat_key = _yield_stat_key('platform', 'hunter', province=prov)
                api_tasks.append((stat_key, 'Hunter', 'hunter', '', '', prov, _run_with_key_rotation('hunter', hunter_scan, hq, target, session=scan_session, stats=stats), stats, target))
            elif "hunter" in enabled_platforms:
                _log("[采集] Hunter 已启用但未配置 API Key，跳过")
            if "daydaymap" in enabled_platforms and ddm_key:
                stats = {}
                target = _target_for("daydaymap")
                stat_key = _yield_stat_key('platform', 'daydaymap', province=prov)
                api_tasks.append((stat_key, 'DayDayMap', 'daydaymap', '', '', prov, _run_with_key_rotation('daydaymap', daydaymap_scan, ddm_q, target, session=scan_session, stats=stats), stats, target))
            elif "daydaymap" in enabled_platforms:
                _log("[采集] DayDayMap 已启用但未配置 API Key，跳过")
            if "fofa" in enabled_platforms and fofa_key:
                stats = {}
                target = _target_for("fofa")
                stat_key = _yield_stat_key('platform', 'fofa', province=prov)
                api_tasks.append((stat_key, 'Fofa', 'fofa', '', '', prov, _run_with_key_rotation('fofa', fofa_scan, fofa_q, target, session=scan_session, stats=stats), stats, target))
            elif "fofa" in enabled_platforms:
                _log("[采集] Fofa 已启用但未配置 API Key，跳过")

            if api_tasks:
                labels = ', '.join(f"{n}(目标{target})" for _, n, _, _, _, _, _, _, target in api_tasks)
                _log(f"[采集] ({len(all_raw)}条) 并行扫描: {labels}...")
                async def _run_and_tag(stat_key, name, platform_key, profile, profile_label, stat_prov, coro, stats):
                    try:
                        result = await coro
                        for ch in result:
                            ch['platform'] = name
                            ch['yield_stat_key'] = stat_key
                        _log(_platform_result_log(name, stats, len(result)))
                        yield_stats.append(_build_yield_stat(
                            stat_key, 'platform', platform_key, profile, profile_label, stat_prov, stats, len(result)
                        ))
                        return result
                    except Exception as e:
                        _log(f"[采集] {name} 失败: {e}")
                        yield_stats.append(_build_yield_stat(
                            stat_key, 'platform', platform_key, profile, profile_label, stat_prov, stats, 0
                        ))
                        return []
                results = await asyncio.gather(*[
                    _run_and_tag(stat_key, n, platform_key, profile, profile_label, stat_prov, c, s)
                    for stat_key, n, platform_key, profile, profile_label, stat_prov, c, s, _ in api_tasks
                ])
                for res in results:
                    all_raw.extend(res)
                _log(f"[采集] API 平台完成，本轮获得 {sum(len(r) for r in results)} 条，累计 {len(all_raw)} 条")

        if scan_cfg.get("quality_discovery_enabled", True):
            profile_tasks = []
            enabled_profile_names = set(scan_cfg.get("quality_query_profiles") or [])
            quality_platforms = [
                p for p in (scan_cfg.get("quality_discovery_platforms") or [])
                if p in enabled_platforms
            ]
            if not quality_platforms:
                if scan_cfg.get("cost_saver_mode", True) and not explicit_platforms and "quake" in enabled_platforms:
                    quality_platforms = ["quake"]
                else:
                    quality_platforms = list(enabled_platforms)
            enabled_profiles = [
                profile for profile in QUALITY_QUERY_PROFILES
                if not enabled_profile_names or profile["name"] in enabled_profile_names
            ]
            if quality_platforms and enabled_profiles:
                _log(
                    "[采集] 质量优先查询平台: "
                    f"{quality_platforms}，画像: {', '.join(p['label'] for p in enabled_profiles)}"
                )
            for prov in selected_provs:
                for profile in enabled_profiles:
                    if "quake" in quality_platforms and quake_key:
                        stats = {}
                        target = _quality_target_for("quake", len(enabled_profiles))
                        query = _with_filters(profile["quake"], "quake", prov)
                        stat_key = _yield_stat_key('quality_profile', 'quake', profile["name"], prov)
                        profile_tasks.append((
                            stat_key,
                            _profile_label("Quake 360", profile['label'], prov),
                            "Quake 360",
                            "quake",
                            profile["name"],
                            profile["label"],
                            prov,
                            _run_with_key_rotation('quake', quake_scan, query, target, session=scan_session, stats=stats),
                            stats,
                            target,
                        ))
                    if "hunter" in quality_platforms and hunter_key:
                        stats = {}
                        target = _quality_target_for("hunter", len(enabled_profiles))
                        query = _with_filters(profile["hunter"], "hunter", prov)
                        stat_key = _yield_stat_key('quality_profile', 'hunter', profile["name"], prov)
                        profile_tasks.append((
                            stat_key,
                            _profile_label("Hunter", profile['label'], prov),
                            "Hunter",
                            "hunter",
                            profile["name"],
                            profile["label"],
                            prov,
                            _run_with_key_rotation('hunter', hunter_scan, query, target, session=scan_session, stats=stats),
                            stats,
                            target,
                        ))
                    if "daydaymap" in quality_platforms and ddm_key:
                        stats = {}
                        target = _quality_target_for("daydaymap", len(enabled_profiles))
                        query = _with_filters(profile["daydaymap"], "daydaymap", prov)
                        stat_key = _yield_stat_key('quality_profile', 'daydaymap', profile["name"], prov)
                        profile_tasks.append((
                            stat_key,
                            _profile_label("DayDayMap", profile['label'], prov),
                            "DayDayMap",
                            "daydaymap",
                            profile["name"],
                            profile["label"],
                            prov,
                            _run_with_key_rotation('daydaymap', daydaymap_scan, query, target, session=scan_session, stats=stats),
                            stats,
                            target,
                        ))
                    if "fofa" in quality_platforms and fofa_key:
                        stats = {}
                        target = _quality_target_for("fofa", len(enabled_profiles))
                        query = _with_filters(profile["fofa"], "fofa", prov)
                        stat_key = _yield_stat_key('quality_profile', 'fofa', profile["name"], prov)
                        profile_tasks.append((
                            stat_key,
                            _profile_label("Fofa", profile['label'], prov),
                            "Fofa",
                            "fofa",
                            profile["name"],
                            profile["label"],
                            prov,
                            _run_with_key_rotation('fofa', fofa_scan, query, target, session=scan_session, stats=stats),
                            stats,
                            target,
                        ))

            if profile_tasks:
                labels = ', '.join(f"{name}(目标{target})" for _, name, _, _, _, _, _, _, _, target in profile_tasks)
                _log(f"[采集] ({len(all_raw)}条) 质量优先查询: {labels}...")
                profile_sem = asyncio.Semaphore(4)

                async def _run_quality_profile(stat_key, log_name, platform_name, platform_key, profile_name, profile_label, stat_prov, coro, stats):
                    async with profile_sem:
                        try:
                            result = await coro
                            for ch in result:
                                ch['platform'] = platform_name
                                ch['discovery_profile'] = log_name
                                ch['yield_stat_key'] = stat_key
                            _log(_platform_result_log(log_name, stats, len(result)))
                            yield_stats.append(_build_yield_stat(
                                stat_key, 'quality_profile', platform_key, profile_name, profile_label, stat_prov, stats, len(result)
                            ))
                            return result
                        except Exception as e:
                            _log(f"[采集] {log_name} 失败: {e}")
                            yield_stats.append(_build_yield_stat(
                                stat_key, 'quality_profile', platform_key, profile_name, profile_label, stat_prov, stats, 0
                            ))
                            return []

                results = await asyncio.gather(*[
                    _run_quality_profile(stat_key, log_name, platform_name, platform_key, profile_name, profile_label, stat_prov, coro, stats)
                    for stat_key, log_name, platform_name, platform_key, profile_name, profile_label, stat_prov, coro, stats, _ in profile_tasks
                ])
                for res in results:
                    all_raw.extend(res)
                _log(f"[采集] 质量优先查询完成，本轮获得 {sum(len(r) for r in results)} 条，累计 {len(all_raw)} 条")

        # 独立平台扫描（ZHGX, JSMpeg, Tvheadend, IPTV互动, DDGS）也并行执行
        independent_tasks = []
        indep_size = size or scan_cfg.get("quake_size", 200)

        if enabled_platforms and not scan_cfg.get("cost_saver_mode", True):
            independent_tasks.append(('ZHGX', zhgx_scan(indep_size, session=scan_session)))
        elif enabled_platforms:
            _log("[采集] 省积分模式：跳过独立 ZHGX 扫描")

        # JSMpeg 全国扫描（只执行一次，不限省份）
        if scan_cfg.get("cost_saver_mode", True) and 'jsmpeg' not in (scan_cfg.get("quality_query_profiles") or []):
            _log("[采集] 省积分模式：跳过独立 JSMpeg 扫描")
        else:
            independent_tasks.append(('JSMpeg', jsmpeg_streamer_scan(province=None, operator=operator if operator else None, size=indep_size, session=scan_session)))

        if hunter_key and "hunter" in enabled_platforms:
            independent_tasks.append(('Tvheadend', _run_with_key_rotation('hunter', tvheadend_scan, None, 30, session=scan_session)))
            independent_tasks.append(('IPTV互动', _run_with_key_rotation('hunter', iptv_interactive_scan, None, 30, session=scan_session)))

        if ddgs_enabled:
            independent_tasks.append(('DDGS', ddgs_scan(None, indep_size, session=scan_session)))

        if independent_tasks:
            _log(f"[采集] ({len(all_raw)}条) 并行扫描独立平台: {', '.join(n for n, _ in independent_tasks)}...")
            async def _run_independent(name, coro):
                try:
                    result = await asyncio.wait_for(coro, timeout=PLATFORM_TIMEOUT)
                    for ch in result:
                        if name == 'JSMpeg':
                            ch['platform'] = ch.pop('scan_source', 'Quake 360')
                        else:
                            ch['platform'] = name
                    _log(f"[采集] {name} 完成：提取频道 {len(result)} 条")
                    return result
                except asyncio.TimeoutError:
                    _log(f"[采集] {name} 超时，放弃")
                    return []
                except Exception as e:
                    _log(f"[采集] {name} 失败: {e}")
                    return []
            results = await asyncio.gather(*[_run_independent(n, c) for n, c in independent_tasks])
            for res in results:
                all_raw.extend(res)
            _log(f"[采集] 独立平台完成，本轮获得 {sum(len(r) for r in results)} 条，累计 {len(all_raw)} 条")

        # 域名/IP 扫描
        _log(f"[采集] ({len(all_raw)}条) 开始域名/IP扫描...")
        try:
            from ..domain_ip_scanner import domain_ip_scan
            domain_entries = await domain_ip_scan(session=scan_session)
            scan_ports = scan_cfg.get(
                'scan_ports', [8080, 80, 443, 9981, 8888, 8000, 9090, 3000, 5000, 8443])
            for ent in domain_entries:
                ip = ent['ip']
                for port in scan_ports:
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
    invalid_url_count = 0
    invalid_name_count = 0
    blacklisted_count = 0
    for ent in all_raw:
        url = clean_url(ent.get('url', ''))
        name = ent.get('name', '')
        if not url:
            invalid_url_count += 1
            continue
        if not is_valid_channel_name(name):
            invalid_name_count += 1
            continue
        if is_blacklisted(name):
            blacklisted_count += 1
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

    dropped = invalid_url_count + invalid_name_count + blacklisted_count
    if dropped:
        _log(
            f"[采集] 清洗丢弃 {dropped} 条：无效URL {invalid_url_count}，"
            f"无效频道名 {invalid_name_count}，黑名单 {blacklisted_count}"
        )
    clean_counts = {}
    for ent in clean:
        stat_key = ent.get('yield_stat_key')
        if stat_key:
            clean_counts[stat_key] = clean_counts.get(stat_key, 0) + 1
    for row in yield_stats:
        stat_key = row.get('stat_key')
        row['cleaned_channels'] = clean_counts.get(stat_key, 0)
    _log(f"[采集] 全部平台扫描完成，原始 {len(all_raw)} 条，清洗后 {len(clean)} 条")
    end_c_segment_budget(c_segment_budget_token)
    return clean, actual_platforms, yield_stats

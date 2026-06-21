# -*- coding: utf-8 -*-
"""web 包 — 结果文件生成（TXT / M3U）。

提取自 web.py 的结果生成逻辑。
"""
import collections
import re as _re

from engine import load_config, resolve_output_update_time


def _sanitize_m3u_attr(value):
    """转义 M3U EXTINF 属性中的特殊字符，防止属性注入。"""
    if not value:
        return value
    # 移除双引号和换行符，避免破坏 EXTINF 属性格式
    return _re.sub(r'["\n\r]', '', str(value))


def _result_sort_key(result):
    from engine.test_engine import calculate_quality_score
    score = result.get('quality_score')
    if score is None:
        bandwidth = result.get('bandwidth_MBps') or 0
        latency = result.get('connection_latency_ms')
        score = calculate_quality_score(bandwidth, latency)
    try:
        bandwidth = float(result.get('bandwidth_MBps') or 0)
    except (TypeError, ValueError):
        bandwidth = 0
    try:
        latency_sort = float(result.get('connection_latency_ms'))
    except (TypeError, ValueError):
        latency_sort = 999999999
    return (-float(score or 0), -bandwidth, latency_sort, result.get('url', ''))


def _get_max_urls_per_channel():
    cfg = load_config()
    try:
        return max(0, int(cfg.get('max_urls_per_channel', 0) or 0))
    except (TypeError, ValueError):
        return 0


def _group_passed_results(passed_results):
    channels = collections.OrderedDict()
    for r in sorted(passed_results, key=_result_sort_key):
        ch = r['channel']
        if ch not in channels:
            channels[ch] = []
        channels[ch].append(r)
    return channels


def _results_for_channel(ch, channels, name_to_canonical=None, regex_aliases=None):
    results = channels.get(ch, [])
    if not results and name_to_canonical:
        from engine.alias import match_channel_name
        canonical = match_channel_name(ch, name_to_canonical, regex_aliases)
        if canonical and canonical != ch:
            results = channels.get(canonical, [])
    max_urls = _get_max_urls_per_channel()
    if max_urls > 0:
        return results[:max_urls]
    return results


def _generate_result_txt(passed_results, fallback_update_time=None):
    """从通过的结果动态生成 result.txt 格式内容。"""
    channels = _group_passed_results(passed_results)

    selected_results = []
    body_lines = []

    try:
        from engine.test_engine import parse_demo_file
        from engine.alias import load_aliases
        _, name_to_canonical, regex_aliases = load_aliases()
        demo = parse_demo_file()
        for genre, ch_list in demo:
            genre_lines = []
            genre_results = []
            for ch in ch_list:
                for result in _results_for_channel(ch, channels, name_to_canonical, regex_aliases):
                    genre_lines.append(f'{ch},{result["url"]}')
                    genre_results.append(result)
            if genre_lines:
                body_lines.append(f'{genre},#genre#')
                body_lines.extend(genre_lines)
                body_lines.append('')
                selected_results.extend(genre_results)
    except Exception:
        max_urls = _get_max_urls_per_channel()
        for ch, results in channels.items():
            if max_urls > 0:
                results = results[:max_urls]
            for result in results:
                body_lines.append(f'{ch},{result["url"]}')
                selected_results.append(result)

    update_time_str = resolve_output_update_time(selected_results, fallback_update_time)
    lines = [
        '🕘️更新时间,#genre#',
        f'{update_time_str},邮箱联系',
        '',
    ]
    lines.extend(body_lines)
    return '\n'.join(lines)


def _generate_result_m3u(passed_results, fallback_update_time=None):
    """从通过的结果动态生成 result.m3u 格式内容。"""
    channels = _group_passed_results(passed_results)

    cfg = load_config()
    logo_base = cfg.get('logo_base_url', 'https://www.xn--rgv465a.top/tvlogo')
    epg_url = cfg.get('epg_url', '')
    selected_results = []
    body_lines = []

    try:
        from engine.test_engine import parse_demo_file
        from engine.alias import load_aliases
        _, name_to_canonical, regex_aliases = load_aliases()
        demo = parse_demo_file()
        for genre, ch_list in demo:
            for ch in ch_list:
                for result in _results_for_channel(ch, channels, name_to_canonical, regex_aliases):
                    safe_ch = _sanitize_m3u_attr(ch)
                    safe_genre = _sanitize_m3u_attr(genre)
                    body_lines.append(
                        f'#EXTINF:-1 tvg-id="{safe_ch}" tvg-name="{safe_ch}" '
                        f'tvg-logo="{logo_base}/{safe_ch}.png" '
                        f'group-title="{safe_genre}",{safe_ch}'
                    )
                    body_lines.append(result['url'])
                    selected_results.append(result)
    except Exception:
        max_urls = _get_max_urls_per_channel()
        for ch, results in channels.items():
            if max_urls > 0:
                results = results[:max_urls]
            for result in results:
                safe_ch = _sanitize_m3u_attr(ch)
                body_lines.append(
                    f'#EXTINF:-1 tvg-id="{safe_ch}" tvg-name="{safe_ch}" '
                    f'tvg-logo="{logo_base}/{safe_ch}.png" '
                    f'group-title="默认",{safe_ch}'
                )
                body_lines.append(result['url'])
                selected_results.append(result)

    update_time_str = resolve_output_update_time(selected_results, fallback_update_time)
    epg_header = f'#EXTM3U x-tvg-url="{epg_url}"' if epg_url else '#EXTM3U'
    lines = [epg_header]
    lines.append(
        f'#EXTINF:-1 tvg-id="更新时间" tvg-name="更新时间" '
        f'group-title="🕘️更新时间",{update_time_str}'
    )
    lines.append('http://localhost/update_time')
    lines.extend(body_lines)
    return '\n'.join(lines)

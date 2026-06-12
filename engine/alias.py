# -*- coding: utf-8 -*-
"""
频道别名共享模块。
提供别名加载、频道名匹配、CCTV 归一化等功能，供测速模块和扫描模块共用。
"""
import re

# 模块级缓存，首次调用 load_aliases() 后填充
_name_to_canonical = {}
_regex_aliases = []
_canonical_to_aliases = {}


def load_aliases():
    """
    从数据库读取频道别名，解析并缓存。
    返回 (canonical_to_aliases, name_to_canonical, regex_aliases)。
    """
    global _name_to_canonical, _regex_aliases, _canonical_to_aliases
    from database import get_config_data
    content = get_config_data('alias')
    canonical_to_aliases = {}
    name_to_canonical = {}
    regex_aliases = []
    for line in content.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = [p.strip() for p in line.split(',') if p.strip()]
        if not parts:
            continue
        canonical = parts[0]
        aliases = parts[1:]
        canonical_to_aliases[canonical] = aliases
        name_to_canonical[canonical] = canonical
        for alias in aliases:
            if alias.startswith('re:'):
                try:
                    regex_aliases.append((re.compile(alias[3:], re.IGNORECASE), canonical))
                except re.error:
                    continue
            else:
                name_to_canonical[alias] = canonical
    # 写入模块缓存
    _canonical_to_aliases = canonical_to_aliases
    _name_to_canonical = name_to_canonical
    _regex_aliases = regex_aliases
    return canonical_to_aliases, name_to_canonical, regex_aliases


def match_channel_name(name, name_to_canonical=None, regex_aliases=None):
    """
    根据别名表匹配频道名称，返回主名；无匹配返回 None。
    不传 name_to_canonical/regex_aliases 时使用模块缓存。
    """
    if not name:
        return None
    ntc = name_to_canonical if name_to_canonical is not None else _name_to_canonical
    ra = regex_aliases if regex_aliases is not None else _regex_aliases
    # 精确匹配（O(1)）
    if name in ntc:
        return ntc[name]
    # 正则匹配（预编译）
    if ra:
        for pattern, canonical in ra:
            if pattern.match(name):
                return canonical
    return None


def get_cached_aliases():
    """返回当前缓存的别名数据，未加载时先触发加载。"""
    if not _name_to_canonical:
        load_aliases()
    return _canonical_to_aliases, _name_to_canonical, _regex_aliases


def strip_quality_suffix(name):
    """去除频道名末尾的画质后缀（高清/HD/4K 等）。"""
    name = re.sub(r'\s*(高清|HD|标清|4K|8K|超清|FHD|1080P|720P)$', '', name, flags=re.I).strip()
    name = re.sub(r'卫视\d+$', '卫视', name)
    return name


def normalize_cctv_variant(name):
    """CCTV 频道名后备归一化（处理别名表未覆盖的变体）。"""
    name = name.strip()
    if '野外' in name:
        return "CCTV-10"
    if '法治' in name and 'CCTV' not in name.upper():
        return "CCTV-12"
    if name.startswith('IPTV5+'):
        return "CCTV-5+"
    m = re.search(r'中央([一二三四五六七八九十]+)套', name)
    if m:
        num_map = {
            "一": "1", "二": "2", "三": "3", "四": "4", "五": "5",
            "六": "6", "七": "7", "八": "8", "九": "9", "十": "10",
            "十一": "11", "十二": "12", "十三": "13", "十四": "14",
            "十五": "15", "十六": "16", "十七": "17"
        }
        num = num_map.get(m.group(1))
        if num:
            return f"CCTV-{num}"
    m = re.search(r'CCTV[-]?(\d+)', name, re.I)
    if m:
        num = m.group(1)
        if num == '5' and '+' in name:
            return "CCTV-5+"
        return f"CCTV-{num}"
    return name

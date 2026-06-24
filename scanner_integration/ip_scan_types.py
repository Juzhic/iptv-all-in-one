# -*- coding: utf-8 -*-
"""
IP扫描类型定义模块
定义各种IPTV扫描类型的检测路径和配置
"""

# 扫描类型配置
SCAN_TYPES = {
    "ALL": {
        "name": "全部扫描",
        "description": "尝试所有已知IPTV接口路径",
        "paths": [
            "/iptv/live/zh_cn.js",
            "/iptv/live/1000.json?key=txiptv",
            "/iptv/live/1000.json",
            "/ZHGXTV/Public/json/live_interface.txt",
            "/streamer/list",
            "/api/channels",
            "/channels",
            "/channel_list.json",
            "/playlist?profile=pass",
            "/getChannelList",
            "/iptv/live/",
            "/api/live/channels",
            "/live/channels.json",
        ]
    },
    "2380": {
        "name": "2380端口",
        "port": 2380,
        "paths": [
            "/iptv/live/zh_cn.js",
            "/iptv/live/1000.json?key=txiptv",
            "/ZHGXTV/Public/json/live_interface.txt",
            "/getChannelList",
        ]
    },
    "HOTEL": {
        "name": "酒店IPTV",
        "paths": [
            "/iptv/live/zh_cn.js",
            "/iptv/live/1000.json?key=txiptv",
            "/ZHGXTV/Public/json/live_interface.txt",
            "/getChannelList",
            "/api/channels",
            "/channels",
        ]
    },
    "MULTICAST": {
        "name": "组播地址",
        "check_type": "multicast",
        "paths": [
            "/udpxy/chanlist",
            "/udp/chanlist",
            "/rtp/chanlist",
            "/udp/",
            "/rtp/",
            "/igmp/",
        ]
    },
    "MIGU": {
        "name": "咪咕视频",
        "paths": [
            "/migu/playlist.m3u8",
            "/migu/live/",
            "/api/migu/channels",
            "/migu/channels.json",
        ]
    },
    "ICNTV": {
        "name": "ICNTV",
        "paths": [
            "/icntv/playlist.m3u8",
            "/icntv/channels",
            "/icntv/api/channels",
            "/icntv/live/",
        ]
    },
    "SOCKS5": {
        "name": "SOCKS5代理",
        "check_type": "socks5",
        "port": 1080,
        "paths": []
    }
}

# 默认端口列表
DEFAULT_PORTS = [4022, 7088, 5140, 8888, 2380, 80, 443, 8080, 8000, 9090, 3000, 5000, 8443]

# 预设端口组
PORT_PRESETS = {
    "常用IPTV": [4022, 7088, 5140, 8888, 2380],
    "Web服务": [80, 443, 8080, 8000, 9090],
    "流媒体": [3000, 5000, 8443, 9981],
    "全部": DEFAULT_PORTS,
}

# IPTV JSON接口路径（用于频道提取）
IPTV_JSON_PATHS = [
    "/iptv/live/1000.json?key=txiptv",
    "/iptv/live/1000.json",
    "/ZHGXTV/Public/json/live_interface.txt",
    "/streamer/list",
    "/api/channels",
    "/channels",
    "/channel_list.json",
    "/getChannelList",
    "/api/live/channels",
    "/live/channels.json",
]

# IPTV M3U接口路径
IPTV_M3U_PATHS = [
    "/iptv/live/zh_cn.js",
    "/playlist?profile=pass",
    "/udpxy/chanlist",
    "/udp/chanlist",
    "/rtp/chanlist",
    "/migu/playlist.m3u8",
    "/icntv/playlist.m3u8",
]


def get_scan_type_config(scan_type: str) -> dict:
    """获取扫描类型配置"""
    return SCAN_TYPES.get(scan_type, {})


def get_all_paths(scan_types: list) -> list:
    """获取所有扫描类型的检测路径（去重）"""
    paths = []
    seen = set()
    
    for scan_type in scan_types:
        config = SCAN_TYPES.get(scan_type, {})
        for path in config.get("paths", []):
            if path not in seen:
                paths.append(path)
                seen.add(path)
    
    return paths


def get_default_port_for_type(scan_type: str) -> int:
    """获取扫描类型的默认端口"""
    config = SCAN_TYPES.get(scan_type, {})
    return config.get("port", 80)

# -*- coding: utf-8 -*-
"""
IP扫描引擎核心模块
支持批量IP/域名输入，多端口扫描，多种IPTV系统检测
"""

import asyncio
import json
import re
import time
import logging
from urllib.parse import urljoin

import aiohttp

from .ip_scan_types import (
    SCAN_TYPES, DEFAULT_PORTS, PORT_PRESETS,
    IPTV_JSON_PATHS, IPTV_M3U_PATHS,
    get_scan_type_config, get_all_paths
)
from .network import get_session

logger = logging.getLogger(__name__)


class IPScanner:
    """IP扫描引擎核心"""
    
    def __init__(self, config=None):
        self.config = config or {}
        self.workers = self.config.get('workers', 16)
        self.rate_limit = self.config.get('rate_limit', 5000)
        self.http_concurrent = self.config.get('http_concurrent', 50)
        self.timeout = self.config.get('timeout', 3600)
        self._stop_requested = False
        
    def request_stop(self):
        """请求停止扫描"""
        self._stop_requested = True
        logger.info("[IP扫描] 收到停止请求")
        
    def clear_stop(self):
        """清除停止标志"""
        self._stop_requested = False
        
    async def scan_targets(self, targets_text, scan_types, ports, log_fn=None):
        """主扫描入口
        
        Args:
            targets_text: 输入文本（IP:PORT/纯IP/域名，每行一个）
            scan_types: 扫描类型列表 ['ALL', 'HOTEL', ...]
            ports: 端口列表 [8080, 80, ...]
            log_fn: 日志回调函数
            
        Returns:
            扫描结果列表
        """
        self._stop_requested = False
        
        # 1. 解析输入
        targets = self._parse_targets(targets_text)
        if log_fn:
            log_fn(f"[IP扫描] 解析到 {len(targets)} 个目标")
        
        if not targets:
            if log_fn:
                log_fn("[IP扫描] 没有有效目标，扫描结束")
            return []
        
        # 2. 端口展开
        expanded = self._expand_ports(targets, ports)
        if log_fn:
            log_fn(f"[IP扫描] 端口展开后 {len(expanded)} 个目标")
        
        # 3. 并发扫描
        results = await self._concurrent_scan(expanded, scan_types, log_fn)
        
        # 4. 汇总结果
        alive_count = sum(1 for r in results if r['alive'])
        channel_count = sum(r['channel_count'] for r in results)
        if log_fn:
            log_fn(f"[IP扫描] 完成！存活: {alive_count}/{len(results)}, 频道: {channel_count}")
        
        return results
    
    def _parse_targets(self, text):
        """解析输入文本
        
        支持格式：
        - IP:PORT (如 192.168.1.1:8080)
        - 纯IP (如 192.168.1.1)
        - 域名 (如 example.com)
        - 域名:PORT (如 example.com:8080)
        """
        targets = []
        seen = set()
        
        for line in text.strip().split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            # 去除行号前缀（如果有）
            if ': ' in line and line.split(': ')[0].isdigit():
                line = line.split(': ', 1)[1]
            
            # 解析 IP:PORT 或 域名:PORT
            host = None
            port = None
            has_port = False
            
            # 处理 IPv6 地址 [::1]:port 格式
            if line.startswith('['):
                match = re.match(r'\[([^\]]+)\]:(\d+)', line)
                if match:
                    host = match.group(1)
                    port = int(match.group(2))
                    has_port = True
                else:
                    match = re.match(r'\[([^\]]+)\]', line)
                    if match:
                        host = match.group(1)
            elif ':' in line:
                parts = line.rsplit(':', 1)
                if len(parts) == 2:
                    host_part = parts[0]
                    port_part = parts[1]
                    try:
                        port = int(port_part)
                        host = host_part
                        has_port = True
                    except ValueError:
                        # 不是端口，可能是域名
                        host = line
                else:
                    host = line
            else:
                host = line
            
            if host:
                # 验证host格式
                host = host.strip()
                if host and host not in seen:
                    key = f"{host}:{port}" if has_port else host
                    if key not in seen:
                        targets.append({
                            'host': host,
                            'port': port,
                            'has_port': has_port
                        })
                        seen.add(key)
        
        return targets
    
    def _expand_ports(self, targets, default_ports):
        """展开端口
        
        如果目标已指定端口，使用指定端口
        否则使用默认端口列表展开
        """
        expanded = []
        seen = set()
        
        for t in targets:
            if t['has_port']:
                key = f"{t['host']}:{t['port']}"
                if key not in seen:
                    expanded.append({'host': t['host'], 'port': t['port']})
                    seen.add(key)
            else:
                for port in default_ports:
                    key = f"{t['host']}:{port}"
                    if key not in seen:
                        expanded.append({'host': t['host'], 'port': port})
                        seen.add(key)
        
        return expanded
    
    async def _concurrent_scan(self, targets, scan_types, log_fn):
        """并发扫描"""
        results = []
        sem = asyncio.Semaphore(self.http_concurrent)
        processed = 0
        alive_count = 0
        total = len(targets)
        
        # 批次大小
        batch_size = 50
        
        timeout = aiohttp.ClientTimeout(total=10, connect=3)
        connector = aiohttp.TCPConnector(limit=self.http_concurrent, limit_per_host=2)
        
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            # 分批处理
            for i in range(0, total, batch_size):
                if self._stop_requested:
                    if log_fn:
                        log_fn(f"[IP扫描] 已停止，已完成 {processed}/{total}")
                    break
                
                batch = targets[i:i+batch_size]
                tasks = []
                
                for t in batch:
                    tasks.append(self._scan_one_with_sem(session, sem, t['host'], t['port'], scan_types))
                
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)
                
                for result in batch_results:
                    if isinstance(result, Exception):
                        logger.debug(f"[IP扫描] 任务异常: {result}")
                        continue
                    if result is not None:
                        results.append(result)
                        processed += 1
                        if result['alive']:
                            alive_count += 1
                
                # 进度日志
                if log_fn and (i + batch_size) % 200 == 0:
                    log_fn(f"[IP扫描] 进度: {processed}/{total}, 存活: {alive_count}")
                
                # 限流控制
                if self.rate_limit < 10000:
                    delay = batch_size / self.rate_limit
                    await asyncio.sleep(min(delay, 0.1))
        
        return results
    
    async def _scan_one_with_sem(self, session, sem, host, port, scan_types):
        """带信号量的单个目标扫描"""
        async with sem:
            if self._stop_requested:
                return None
            return await self._check_target(session, host, port, scan_types)
    
    async def _check_target(self, session, host, port, scan_types):
        """检测单个目标"""
        start_time = time.time()
        
        result = {
            'target': f"{host}:{port}",
            'ip': host,
            'port': port,
            'alive': False,
            'http_status': 0,
            'response_time_ms': 0,
            'channels_json': '[]',
            'channel_count': 0,
            'scan_type_matched': '',
            'error': ''
        }
        
        try:
            # HTTP存活检测
            url = f"http://{host}:{port}/"
            async with session.get(url, allow_redirects=True) as resp:
                result['http_status'] = resp.status
                result['response_time_ms'] = (time.time() - start_time) * 1000
                
                # 2xx 或 3xx 都认为是存活
                if 200 <= resp.status < 400:
                    result['alive'] = True
                    
                    # 尝试提取频道
                    channels, matched_type = await self._extract_channels(session, host, port, scan_types)
                    if channels:
                        result['channels_json'] = json.dumps(channels, ensure_ascii=False)
                        result['channel_count'] = len(channels)
                        result['scan_type_matched'] = matched_type
                        
        except asyncio.TimeoutError:
            result['error'] = '连接超时'
        except aiohttp.ClientError as e:
            result['error'] = f'连接错误: {str(e)[:50]}'
        except Exception as e:
            result['error'] = f'未知错误: {str(e)[:50]}'
            
        return result
    
    async def _extract_channels(self, session, host, port, scan_types):
        """从目标提取频道
        
        Returns:
            (channels_list, matched_scan_type)
        """
        # 获取所有需要检测的路径
        all_paths = get_all_paths(scan_types)
        
        # 先尝试JSON接口
        for path in IPTV_JSON_PATHS:
            if self._stop_requested:
                return [], ''
            
            try:
                url = f"http://{host}:{port}{path}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        channels = self._parse_json_channels(data, host, port)
                        if channels:
                            # 确定匹配的扫描类型
                            matched_type = self._determine_scan_type(path, scan_types)
                            return channels, matched_type
            except:
                continue
        
        # 再尝试M3U接口
        for path in IPTV_M3U_PATHS:
            if self._stop_requested:
                return [], ''
            
            try:
                url = f"http://{host}:{port}{path}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        channels = self._parse_m3u_channels(data, host, port)
                        if channels:
                            matched_type = self._determine_scan_type(path, scan_types)
                            return channels, matched_type
            except:
                continue
        
        return [], ''
    
    def _determine_scan_type(self, path, scan_types):
        """根据路径确定匹配的扫描类型"""
        for scan_type in scan_types:
            config = SCAN_TYPES.get(scan_type, {})
            if path in config.get('paths', []):
                return scan_type
        
        # 默认返回第一个扫描类型
        return scan_types[0] if scan_types else 'ALL'
    
    def _parse_json_channels(self, data, host, port):
        """解析JSON格式频道数据"""
        try:
            # 尝试不同编码
            for encoding in ['utf-8', 'gbk', 'gb2312']:
                try:
                    text = data.decode(encoding)
                    json_data = json.loads(text)
                    break
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
            else:
                return []
            
            channels = []
            
            # 格式1: {"data": [{"name": "...", "url": "..."}]}
            if isinstance(json_data, dict) and 'data' in json_data:
                data_list = json_data['data']
                if isinstance(data_list, list):
                    for ch in data_list:
                        if isinstance(ch, dict):
                            name = ch.get('name', ch.get('title', ''))
                            url = ch.get('url', ch.get('stream', ''))
                            if name and url:
                                url = self._normalize_url(url, host, port)
                                channels.append({'name': name, 'url': url})
            
            # 格式2: [{"name": "...", "url": "..."}]
            elif isinstance(json_data, list):
                for ch in json_data:
                    if isinstance(ch, dict):
                        name = ch.get('name', ch.get('title', ''))
                        url = ch.get('url', ch.get('stream', ''))
                        if name and url:
                            url = self._normalize_url(url, host, port)
                            channels.append({'name': name, 'url': url})
            
            # 格式3: {"channels": [...]}
            elif isinstance(json_data, dict) and 'channels' in json_data:
                for ch in json_data['channels']:
                    if isinstance(ch, dict):
                        name = ch.get('name', ch.get('title', ''))
                        url = ch.get('url', ch.get('stream', ''))
                        if name and url:
                            url = self._normalize_url(url, host, port)
                            channels.append({'name': name, 'url': url})
            
            return channels[:500]  # 限制最大频道数
            
        except Exception as e:
            logger.debug(f"[IP扫描] JSON解析失败: {e}")
            return []
    
    def _parse_m3u_channels(self, data, host, port):
        """解析M3U格式频道数据"""
        try:
            # 尝试不同编码
            for encoding in ['utf-8', 'gbk', 'gb2312']:
                try:
                    text = data.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                return []
            
            channels = []
            lines = text.split('\n')
            
            current_name = None
            for line in lines:
                line = line.strip()
                
                if line.startswith('#EXTINF:'):
                    # 提取频道名
                    match = re.search(r',(.+)$', line)
                    if match:
                        current_name = match.group(1).strip()
                    # 也尝试从 tvg-name 提取
                    tvg_match = re.search(r'tvg-name="([^"]*)"', line)
                    if tvg_match and not current_name:
                        current_name = tvg_match.group(1).strip()
                
                elif line and not line.startswith('#') and current_name:
                    # 这是URL行
                    url = self._normalize_url(line, host, port)
                    channels.append({'name': current_name, 'url': url})
                    current_name = None
            
            return channels[:500]  # 限制最大频道数
            
        except Exception as e:
            logger.debug(f"[IP扫描] M3U解析失败: {e}")
            return []
    
    def _normalize_url(self, url, host, port):
        """规范化URL"""
        if not url:
            return url
        
        # 已经是完整URL
        if url.startswith('http://') or url.startswith('https://'):
            return url
        
        # 相对路径
        if url.startswith('/'):
            return f"http://{host}:{port}{url}"
        
        # 其他情况
        return f"http://{host}:{port}/{url}"


# 全局扫描器实例
_ip_scanner = None
_ip_scan_stop_requested = False


def get_ip_scanner(config=None):
    """获取IP扫描器单例"""
    global _ip_scanner
    if _ip_scanner is None:
        _ip_scanner = IPScanner(config)
    return _ip_scanner


def request_stop_ip_scan():
    """请求停止IP扫描"""
    global _ip_scan_stop_requested
    _ip_scan_stop_requested = True
    scanner = get_ip_scanner()
    scanner.request_stop()


def clear_ip_scan_stop():
    """清除IP扫描停止标志"""
    global _ip_scan_stop_requested
    _ip_scan_stop_requested = False
    scanner = get_ip_scanner()
    scanner.clear_stop()


def is_ip_scan_stop_requested():
    """检查是否请求了停止"""
    return _ip_scan_stop_requested

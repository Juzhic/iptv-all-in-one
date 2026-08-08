# -*- coding: utf-8 -*-
"""
IP扫描引擎核心模块
支持批量IP/域名输入，多端口扫描，多种IPTV系统检测
"""

import asyncio
import ipaddress
import json
import re
import time
import logging

from .ip_scan_types import (
    SCAN_TYPES, DEFAULT_PORTS, PORT_PRESETS,
    IPTV_JSON_PATHS, IPTV_M3U_PATHS,
    get_scan_type_config, get_all_paths
)
from .safe_http import (
    DEFAULT_MAX_RESPONSE_BYTES,
    NetworkPolicyError,
    safe_fetch,
    validate_host_name,
    validate_ip_address,
)

logger = logging.getLogger(__name__)

MAX_LOGICAL_TARGETS = 1000
MAX_TARGET_TEXT_BYTES = 512 * 1024
MAX_PORTS = 64
MAX_EXPANDED_TARGETS = 20000
MAX_RESPONSE_BYTES = DEFAULT_MAX_RESPONSE_BYTES
MAX_RESPONSE_LINES = 50000
MAX_CHANNELS = 50000


class IPScanInputError(ValueError):
    """IP 扫描请求超过资源边界或包含被禁止的目标。"""


class IPScanner:
    """IP扫描引擎核心"""
    
    def __init__(self, config=None):
        self.config = config or {}
        self.workers = self._config_int('workers', 16, 1, 100)
        self.rate_limit = self._config_int('rate_limit', 5000, 100, 50000)
        self.http_concurrent = self._config_int('http_concurrent', 50, 1, 500)
        self.timeout = self._config_int('timeout', 3600, 60, 86400)
        self._stop_requested = False

    def _config_int(self, key, default, min_value, max_value):
        try:
            value = int(self.config.get(key, default))
        except (TypeError, ValueError):
            value = default
        return max(min_value, min(max_value, value))
        
    def request_stop(self):
        """请求停止扫描"""
        self._stop_requested = True
        logger.info("[IP扫描] 收到停止请求")
        
    def clear_stop(self):
        """清除停止标志"""
        self._stop_requested = False
        
    async def scan_targets(self, targets_text, scan_types, ports, log_fn=None, progress_fn=None):
        """主扫描入口
        
        Args:
            targets_text: 输入文本（IP:PORT/纯IP/域名，每行一个）
            scan_types: 扫描类型列表 ['ALL', 'HOTEL', ...]
            ports: 端口列表 [8080, 80, ...]
            log_fn: 日志回调函数
            
        Returns:
            扫描结果列表
        """
        # 1. 解析输入
        targets, ports, expanded = self.validate_request(targets_text, ports)
        if log_fn:
            log_fn(f"[IP扫描] 解析到 {len(targets)} 个目标")
        
        if not targets:
            if log_fn:
                log_fn("[IP扫描] 没有有效目标，扫描结束")
            return []
        
        # 2. 端口展开
        if log_fn:
            log_fn(f"[IP扫描] 端口展开后 {len(expanded)} 个目标")
        
        # 3. 并发扫描
        results = await self._concurrent_scan(expanded, scan_types, log_fn, progress_fn)
        
        # 4. 汇总结果
        alive_count = sum(1 for r in results if r['alive'])
        channel_count = sum(r['channel_count'] for r in results)
        if log_fn:
            log_fn(f"[IP扫描] 完成！存活: {alive_count}/{len(results)}, 频道: {channel_count}")
        
        return results

    def validate_request(self, targets_text, ports):
        """Validate and expand one scan request without performing network I/O."""
        targets = self._parse_targets(targets_text)
        normalized_ports = self._validate_ports(ports)
        expanded = self._expand_ports(targets, normalized_ports)
        return targets, normalized_ports, expanded

    @staticmethod
    def _validate_ports(ports):
        if not isinstance(ports, (list, tuple, set)):
            raise IPScanInputError("端口必须是列表")
        normalized = []
        seen = set()
        for raw_port in ports:
            if isinstance(raw_port, bool):
                raise IPScanInputError("端口必须是 1-65535 的整数")
            try:
                port = int(raw_port)
            except (TypeError, ValueError) as exc:
                raise IPScanInputError("端口必须是 1-65535 的整数") from exc
            if not 1 <= port <= 65535:
                raise IPScanInputError("端口必须是 1-65535 的整数")
            if port not in seen:
                normalized.append(port)
                seen.add(port)
                if len(normalized) > MAX_PORTS:
                    raise IPScanInputError(f"端口最多允许 {MAX_PORTS} 个")
        if not normalized:
            raise IPScanInputError("至少需要一个有效端口")
        return normalized

    @staticmethod
    def _validate_target_host(host):
        host = validate_host_name(host)
        try:
            # Literals are checked immediately. RFC1918/ULA are intentional
            # scan targets; loopback, link-local, multicast, unspecified,
            # reserved and metadata addresses remain forbidden.
            return validate_ip_address(host, allow_rfc1918=True)
        except NetworkPolicyError as policy_error:
            try:
                ipaddress.ip_address(host.split('%', 1)[0])
            except ValueError:
                pass
            else:
                raise IPScanInputError(str(policy_error)) from policy_error

        try:
            ascii_host = host.encode('idna').decode('ascii')
        except UnicodeError as exc:
            raise IPScanInputError("目标主机名无效") from exc
        if len(ascii_host) > 253:
            raise IPScanInputError("目标主机名过长")
        labels = ascii_host.split('.')
        if any(
            not label or len(label) > 63
            or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?', label)
            for label in labels
        ):
            raise IPScanInputError("目标主机名无效")
        return ascii_host.lower()
    
    def _parse_targets(self, text):
        """解析输入文本
        
        支持格式：
        - IP:PORT (如 192.168.1.1:8080)
        - 纯IP (如 192.168.1.1)
        - 域名 (如 example.com)
        - 域名:PORT (如 example.com:8080)
        """
        if not isinstance(text, str):
            raise IPScanInputError("扫描目标必须是文本")
        if len(text.encode('utf-8')) > MAX_TARGET_TEXT_BYTES:
            raise IPScanInputError("扫描目标文本不能超过 512 KiB")

        logical_lines = [
            line.strip() for line in text.splitlines()
            if line.strip() and not line.strip().startswith('#')
        ]
        if len(logical_lines) > MAX_LOGICAL_TARGETS:
            raise IPScanInputError(f"扫描目标最多允许 {MAX_LOGICAL_TARGETS} 个")

        targets = []
        seen = set()
        
        for line in logical_lines:
            
            # 去除行号前缀（如果有）
            if ': ' in line and line.split(': ')[0].isdigit():
                line = line.split(': ', 1)[1]
            
            # 解析 IP:PORT 或 域名:PORT
            host = None
            port = None
            has_port = False
            
            # 裸 IPv6 地址不带端口；带端口时必须使用 [addr]:port。
            try:
                ipaddress.ip_address(line.split('%', 1)[0])
                host = line
            except ValueError:
                pass

            # 处理 IPv6 地址 [::1]:port 格式
            if host is not None:
                pass
            elif line.startswith('['):
                match = re.fullmatch(r'\[([^\]]+)\]:(\d+)', line)
                if match:
                    host = match.group(1)
                    port = int(match.group(2))
                    has_port = True
                else:
                    match = re.fullmatch(r'\[([^\]]+)\]', line)
                    if match:
                        host = match.group(1)
                    else:
                        raise IPScanInputError(f"目标格式无效: {line[:80]}")
            elif ':' in line:
                if line.count(':') > 1:
                    raise IPScanInputError("IPv6 目标指定端口时必须使用 [地址]:端口")
                parts = line.rsplit(':', 1)
                if len(parts) == 2:
                    host_part = parts[0]
                    port_part = parts[1]
                    try:
                        port = int(port_part)
                        host = host_part
                        has_port = True
                    except ValueError:
                        raise IPScanInputError(f"目标端口无效: {line[:80]}")
                else:
                    host = line
            else:
                host = line
            
            if host:
                host = self._validate_target_host(host.strip())
                if has_port and not 1 <= port <= 65535:
                    raise IPScanInputError("端口必须是 1-65535 的整数")
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
                    if len(expanded) > MAX_EXPANDED_TARGETS:
                        raise IPScanInputError(
                            f"端口展开后的扫描任务最多允许 {MAX_EXPANDED_TARGETS} 个"
                        )
            else:
                for port in default_ports:
                    key = f"{t['host']}:{port}"
                    if key not in seen:
                        expanded.append({'host': t['host'], 'port': port})
                        seen.add(key)
                        if len(expanded) > MAX_EXPANDED_TARGETS:
                            raise IPScanInputError(
                                f"端口展开后的扫描任务最多允许 {MAX_EXPANDED_TARGETS} 个"
                            )
        
        return expanded
    
    async def _concurrent_scan(self, targets, scan_types, log_fn, progress_fn=None):
        """并发扫描"""
        results = []
        sem = asyncio.Semaphore(self.http_concurrent)
        processed = 0
        alive_count = 0
        total = len(targets)
        
        # Batch size controls how many scan tasks are submitted at once.
        batch_size = self.workers
        
        # 分批处理。每个请求由 safe_fetch 创建 DNS 固定的短会话，避免
        # 共享连接池在域名重新解析后绕过目标策略。
        for i in range(0, total, batch_size):
            if self._stop_requested:
                if log_fn:
                    log_fn(f"[IP扫描] 已停止，已完成 {processed}/{total}")
                break
                
            batch = targets[i:i+batch_size]
            tasks = []
                
            for t in batch:
                tasks.append(self._scan_one_with_sem(None, sem, t['host'], t['port'], scan_types))
                
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

            if progress_fn:
                channel_count = sum(r.get('channel_count', 0) for r in results)
                progress_fn({
                    'total': total,
                    'processed': processed,
                    'alive': alive_count,
                    'channels': channel_count,
                    'percent': (processed / total * 100) if total else 0,
                })
                
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
            url = self._build_url(host, port, '/')
            response = await safe_fetch(
                url,
                timeout=10,
                max_bytes=MAX_RESPONSE_BYTES,
                allow_rfc1918=True,
            )
            result['http_status'] = response.status
            result['response_time_ms'] = (time.time() - start_time) * 1000
                
            # safe_fetch follows at most three policy-checked redirects.
            if 200 <= response.status < 400:
                result['alive'] = True
                    
                channels, matched_type = await self._extract_channels(session, host, port, scan_types)
                if channels:
                    result['channels_json'] = json.dumps(channels, ensure_ascii=False)
                    result['channel_count'] = len(channels)
                    result['scan_type_matched'] = matched_type
                        
        except asyncio.TimeoutError:
            result['error'] = '连接超时'
        except NetworkPolicyError as e:
            result['error'] = f'目标被安全策略拒绝: {str(e)[:80]}'
        except Exception as e:
            result['error'] = f'未知错误: {str(e)[:50]}'
            
        return result
    
    async def _extract_channels(self, session, host, port, scan_types):
        """从目标提取频道
        
        Returns:
            (channels_list, matched_scan_type)
        """
        # 先尝试JSON接口
        for path in IPTV_JSON_PATHS:
            if self._stop_requested:
                return [], ''
            
            try:
                url = self._build_url(host, port, path)
                response = await safe_fetch(
                    url, timeout=5, max_bytes=MAX_RESPONSE_BYTES,
                    allow_rfc1918=True,
                )
                if response.status == 200:
                    channels = self._parse_json_channels(response.body, host, port)
                    if channels:
                        matched_type = self._determine_scan_type(path, scan_types)
                        return channels, matched_type
            except Exception:
                continue

        # 再尝试M3U接口
        for path in IPTV_M3U_PATHS:
            if self._stop_requested:
                return [], ''
            
            try:
                url = self._build_url(host, port, path)
                response = await safe_fetch(
                    url, timeout=5, max_bytes=MAX_RESPONSE_BYTES,
                    allow_rfc1918=True,
                )
                if response.status == 200:
                    channels = self._parse_m3u_channels(response.body, host, port)
                    if channels:
                        matched_type = self._determine_scan_type(path, scan_types)
                        return channels, matched_type
            except Exception:
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
                                if len(channels) >= MAX_CHANNELS:
                                    break
            
            # 格式2: [{"name": "...", "url": "..."}]
            elif isinstance(json_data, list):
                for ch in json_data:
                    if isinstance(ch, dict):
                        name = ch.get('name', ch.get('title', ''))
                        url = ch.get('url', ch.get('stream', ''))
                        if name and url:
                            url = self._normalize_url(url, host, port)
                            channels.append({'name': name, 'url': url})
                            if len(channels) >= MAX_CHANNELS:
                                break
            
            # 格式3: {"channels": [...]}
            elif isinstance(json_data, dict) and 'channels' in json_data:
                for ch in json_data['channels']:
                    if isinstance(ch, dict):
                        name = ch.get('name', ch.get('title', ''))
                        url = ch.get('url', ch.get('stream', ''))
                        if name and url:
                            url = self._normalize_url(url, host, port)
                            channels.append({'name': name, 'url': url})
                            if len(channels) >= MAX_CHANNELS:
                                break
            
            return channels[:MAX_CHANNELS]
            
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
            lines = text.splitlines()[:MAX_RESPONSE_LINES]
            
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
            
            return channels[:MAX_CHANNELS]
            
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
            return self._build_url(host, port, url)
        
        # 其他情况
        return self._build_url(host, port, f'/{url}')

    @staticmethod
    def _build_url(host, port, path):
        url_host = f'[{host}]' if ':' in host and not host.startswith('[') else host
        return f"http://{url_host}:{port}{path}"


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

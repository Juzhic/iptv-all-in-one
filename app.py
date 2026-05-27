import time
import threading
import re
import json
import logging
import os
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from FFmpegTest import analyze_iptv_with_ffmpeg, register_timeout as _reg_timeout, clear_timeouts as _clear_timeouts, http_get
from db import init_db, insert_run, migrate_from_json, now_str, timestamp_str

try:
    import psutil
except ImportError:
    psutil = None


# 默认配置（config.json 不存在时使用）
DEFAULT_CONFIG = {
    'test_duration': 15,
    'max_workers': 30,
    'system_bandwidth_limit_MBps': 50,
    'min_bandwidth_MBps': 1.0,
    'bandwidth_compensation_MBps': 2.0,
    'h265_bandwidth_ratio': 0.6,
    'max_urls_per_channel': 10,
    'show_update_time': True,
    'update_time_position': 'top',
    'min_width': 1920,
    'min_height': 1080,
    'output_txt': 'output/result.txt',
    'output_m3u': 'output/result.m3u',
    'run_mode': 'once',
    'run_times': [],
    'run_interval_minutes': 60,
}


def load_config(filepath=None):
    """从数据库加载配置，缺失项使用默认值。首次启动自动从 config.json 迁移。"""
    from db import get_config, migrate_config_from_file
    # 首次启动：尝试从 config.json 迁移
    migrate_config_from_file('config.json', DEFAULT_CONFIG)
    return get_config(DEFAULT_CONFIG)


LOW_RESOLUTION_URL_PATTERNS = (
    ('720p', re.compile(r'(^|[/?&=._-])720p([/?&=._-]|$)', re.IGNORECASE)),
    ('480p', re.compile(r'(^|[/?&=._-])480p([/?&=._-]|$)', re.IGNORECASE)),
    ('sd', re.compile(r'(^|[/?&=._-])sd([/?&=._-]|$)', re.IGNORECASE)),
)


def detect_low_resolution_url(url):
    """识别 URL 中明确标注的低清晰度版本。"""
    for label, pattern in LOW_RESOLUTION_URL_PATTERNS:
        if pattern.search(url):
            return label
    return ''


def get_bandwidth_sample_info(result, duration):
    """返回用于判定带宽补偿的有效采样时长。"""
    sample_seconds = result.get('media_seconds') or result.get('measured_seconds', 0)
    min_sample_seconds = min(3, max(duration, 1))
    return sample_seconds, min_sample_seconds, sample_seconds >= min_sample_seconds


def calculate_quality_score(bandwidth_MBps, connection_latency_ms):
    """按平均带宽和连接延迟计算频道内排序分数。"""
    try:
        bandwidth = float(bandwidth_MBps or 0)
    except (TypeError, ValueError):
        bandwidth = 0.0

    try:
        latency_ms = float(connection_latency_ms)
    except (TypeError, ValueError):
        latency_ms = 3000.0

    latency_seconds = max(latency_ms, 0.0) / 1000
    return round(bandwidth / (1 + latency_seconds), 4)


def _entry_url(entry):
    if isinstance(entry, dict):
        return entry.get('url', '')
    return entry


def _entry_sort_key(entry):
    if not isinstance(entry, dict):
        return (0, 0, 999999999, _entry_url(entry))

    bandwidth = entry.get('bandwidth_MBps', entry.get('speed_MBps', 0))
    latency = entry.get('connection_latency_ms')
    score = entry.get('quality_score')
    if score is None:
        score = calculate_quality_score(bandwidth, latency)
    try:
        bandwidth = float(bandwidth or 0)
    except (TypeError, ValueError):
        bandwidth = 0.0
    try:
        latency_sort = float(latency)
    except (TypeError, ValueError):
        latency_sort = 999999999.0

    return (-float(score or 0), -bandwidth, latency_sort, entry.get('url', ''))


def sort_and_limit_channel_entries(entries, max_count=0):
    """单个频道内按质量排序，并按配置限制输出地址数量。"""
    sorted_entries = sorted(entries, key=_entry_sort_key)
    try:
        max_count = int(max_count or 0)
    except (TypeError, ValueError):
        max_count = 0
    if max_count > 0:
        return sorted_entries[:max_count]
    return sorted_entries


def build_output_urls_from_results(test_results, max_urls_per_channel=0):
    """从完整测速结果生成最终输出用的 {频道: [地址信息]}。"""
    filtered = {}
    seen = {}
    for result in test_results:
        if not result.get('passed'):
            continue
        name = result.get('channel', '')
        url = result.get('url', '')
        if not name or not url:
            continue
        if name not in filtered:
            filtered[name] = []
            seen[name] = set()
        if url in seen[name]:
            continue
        entry = {
            'url': url,
            'bandwidth_MBps': result.get('bandwidth_MBps', 0),
            'connection_latency_ms': result.get('connection_latency_ms'),
            'quality_score': result.get('quality_score'),
        }
        filtered[name].append(entry)
        seen[name].add(url)

    return {
        name: sort_and_limit_channel_entries(entries, max_urls_per_channel)
        for name, entries in filtered.items()
    }


class SystemDownloadLimiter:
    """根据本机总下行带宽决定是否暂停启动新的频道测试。"""

    def __init__(self, limit_mbps=50, sample_interval=1.0, log_interval=10):
        self.limit_mbps = float(limit_mbps or 0)
        self.sample_interval = sample_interval
        self.log_interval = log_interval
        self.enabled = self.limit_mbps > 0 and psutil is not None
        self.current_mbps = 0.0
        self._last_bytes = None
        self._last_time = None
        self._last_log_time = 0

    def refresh(self):
        if not self.enabled:
            return 0.0

        now = time.monotonic()
        bytes_recv = psutil.net_io_counters().bytes_recv
        if self._last_bytes is None:
            self._last_bytes = bytes_recv
            self._last_time = now
            self.current_mbps = 0.0
            return self.current_mbps

        elapsed = now - self._last_time
        if elapsed < self.sample_interval:
            return self.current_mbps

        byte_delta = max(0, bytes_recv - self._last_bytes)
        self.current_mbps = byte_delta / (elapsed * 1_000_000)
        self._last_bytes = bytes_recv
        self._last_time = now
        return self.current_mbps

    def should_pause(self):
        return self.enabled and self.refresh() >= self.limit_mbps

    def log_pause_if_needed(self, logger):
        now = time.monotonic()
        if now - self._last_log_time >= self.log_interval:
            logger.info(
                "总下行 %.2fMB/s >= %.2fMB/s，暂停启动新频道",
                self.current_mbps,
                self.limit_mbps
            )
            self._last_log_time = now


# --- 日志配置模块 ---
class _DBLogHandler(logging.Handler):
    """将日志写入 SQLite 数据库的 logging handler。"""
    def __init__(self):
        super().__init__()
        self.run_id = ''

    def emit(self, record):
        if not self.run_id:
            return
        try:
            from db import insert_log
            insert_log(self.run_id, record.levelname, self.format(record))
        except Exception:
            pass


_db_handler = _DBLogHandler()


def setup_logging(run_id=''):
    """配置日志系统：控制台输出 + 数据库写入。"""
    root_logger = logging.getLogger()
    if root_logger.handlers:
        for handler in root_logger.handlers[:]:
            handler.close()
            root_logger.removeHandler(handler)

    _db_handler.run_id = run_id
    _db_handler.setFormatter(logging.Formatter('%(message)s'))

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            _db_handler,
            logging.StreamHandler()
        ]
    )

    logger = logging.getLogger(__name__)
    logger.info(f"日志系统已启动（数据库 + 控制台）")
    return logger

def fetch_m3u_playlist(url):
    """从指定 URL 获取 M3U 播放列表数据。"""
    try:
        response = http_get(url, timeout=10, stream=False)
        response.raise_for_status()
        return response.text
    except Exception as e:
        print(f"获取 M3U 数据失败：{e}")
        return None


def parse_iptv_addresses(m3u_content):
    """
    解析 M3U 内容，提取 IPTV 组播地址
    :param m3u_content: M3U 格式的内容
    :return: list 包含 (频道信息，URL 地址) 的元组列表
    """
    iptv_list = []
    lines = m3u_content.split('\n')
    
    current_channel = {}
    
    for line in lines:
        line = line.strip()
        
        # 跳过空行和注释（除了 EXTINF）
        if not line or (line.startswith('#') and not line.startswith('#EXTINF')):
            continue
        
        # 解析 EXTINF 行
        if line.startswith('#EXTINF'):
            # 提取频道名称和分组信息
            match = re.search(r'group-title="([^"]*)".*?,(.+)$', line)
            if match:
                current_channel['group'] = match.group(1)
                current_channel['name'] = match.group(2).strip()
            else:
                # 尝试简单的匹配
                parts = line.split(',')
                if len(parts) > 1:
                    current_channel['name'] = parts[-1].strip()
        
        # 解析 URL 行（以 http 开头）
        elif line.startswith('http://') or line.startswith('https://'):
            # 保留 EXTINF 后面的任意 HTTP/HTTPS 播放地址。
            # 有些源是短链、php 入口或带查询参数的中转地址，不能只靠 .m3u8/live/rtp 关键字判断。
            iptv_list.append((current_channel.copy(), line))
            current_channel = {}  # 重置频道信息
    
    return iptv_list


def filter_and_save_playlist(
    iptv_list,
    duration=10,
    max_workers=5,
    progress_callback=None,
    bandwidth_limit_mbps=None,
    config=None,
    on_pass_callback=None,
    run_id='',
    stop_event=None
):
    """
    过滤并保存符合条件的 IPTV 列表（修改版：增加详细日志和进度计算）
    """
    cfg = config or DEFAULT_CONFIG
    if bandwidth_limit_mbps is None:
        bandwidth_limit_mbps = cfg.get('system_bandwidth_limit_MBps', 50)
    min_width = cfg.get('min_width', 1920)
    min_height = cfg.get('min_height', 1080)
    min_bw = cfg.get('min_bandwidth_MBps', 1.0)
    bw_comp = cfg.get('bandwidth_compensation_MBps', 2.0)
    h265_ratio = cfg.get('h265_bandwidth_ratio', 0.6)
    global logger
    filtered_list = []
    test_results = []
    total = len(iptv_list)
    processed = 0
    failed = 0

    logger = setup_logging(run_id)

    logger.info(f"开始测试任务")
    logger.info(f"总频道数: {total}")
    logger.info(f"并发线程数: {max_workers}")
    logger.info(f"单个频道测试时长: {duration}秒")
    channel_timeout = max(duration + 15, int(duration * 1.5))
    logger.info(f"单频道最大等待时间: {channel_timeout}秒")
    download_limiter = SystemDownloadLimiter(bandwidth_limit_mbps)
    if download_limiter.enabled:
        logger.info(f"总下行启动限速: {download_limiter.limit_mbps:.2f}MB/s")
    elif bandwidth_limit_mbps and psutil is None:
        logger.info("总下行启动限速: 未安装 psutil，已关闭")
    else:
        logger.info("总下行启动限速: 已关闭")

    def test_single_channel(args):
        """单个频道测试函数"""
        idx, (channel_info, url) = args
        start_time = time.time()  # 记录开始时间

        try:
            if stop_event and stop_event.is_set():
                return {'index': idx, 'channel_info': channel_info, 'url': url, 'pass': False, 'reason': '任务已终止','duration': time.time() - start_time }
            low_resolution_hint = detect_low_resolution_url(url)
            if low_resolution_hint:
                return {
                    'index': idx,
                    'channel_info': channel_info,
                    'url': url,
                    'pass': False,
                    'duration': time.time() - start_time,
                    'test_result': {
                        'resolution': f"URL标记:{low_resolution_hint}",
                        'speed_MBps': 0,
                        'bandwidth_MBps': 0,
                        'bitrate_mbps': 0,
                        'measured_seconds': 0,
                        'ffmpeg_used': False,
                        'ffmpeg_available': True,
                        'ffmpeg_resolution_found': False,
                        'ffmpeg_error': '',
                        'low_resolution_url': True,
                        'low_resolution_hint': low_resolution_hint,
                        'connection_latency_ms': None,
                        'quality_score': 0,
                        'resolution_pass': False,
                        'bandwidth_pass': False,
                        'resolution_compensation_pass': False
                    }
                }

            result = analyze_iptv_with_ffmpeg(url, duration, min_width=min_width, min_height=min_height)
            if not result or not result.get('success'):
                error_reason = result.get('error', '分析失败') if result else '分析失败'
                return {'index': idx, 'channel_info': channel_info, 'url': url, 'pass': False, 'reason': error_reason,'duration': time.time() - start_time }

            width = result.get('width', 0)
            height = result.get('height', 0)
            bandwidth_MBps = result.get('speed_MBps', 0)
            connection_latency_ms = result.get('connection_latency_ms')
            quality_score = calculate_quality_score(bandwidth_MBps, connection_latency_ms)
            ffmpeg_available = result.get('ffmpeg_available', True)
            ffmpeg_resolution_found = result.get('ffmpeg_resolution_found', width > 0 and height > 0)
            sample_seconds, min_sample_seconds, sample_seconds_pass = get_bandwidth_sample_info(result, duration)

            # H.265/HEVC 编码检测，压缩率更高，相同画质所需带宽更低
            codec = result.get('codec', '')
            is_h265 = codec in ('hevc', 'h265')
            if is_h265:
                effective_min_bw = min_bw * h265_ratio
            else:
                effective_min_bw = min_bw
            effective_bw_comp = bw_comp

            resolution_pass = (width >= min_width and height >= min_height)
            bandwidth_pass = bandwidth_MBps > effective_min_bw
            resolution_compensation_pass = (
                ffmpeg_available
                and (not ffmpeg_resolution_found)
                and bandwidth_MBps >= effective_bw_comp
                and sample_seconds_pass
            )
            passed = (resolution_pass and bandwidth_pass) or resolution_compensation_pass

            return {
                'index': idx, 'channel_info': channel_info, 'url': url, 'pass': passed,'duration': time.time() - start_time ,
                'test_result': {'resolution': f"{width}x{height}", 'speed_MBps': bandwidth_MBps,
                                'bandwidth_MBps': bandwidth_MBps,
                                'bitrate_mbps': result.get('bitrate_mbps', 0),
                                'codec': codec,
                                'is_h265': is_h265,
                                'effective_min_bw': effective_min_bw,
                                'effective_bw_comp': effective_bw_comp,
                                'measured_seconds': result.get('measured_seconds', 0),
                                'media_seconds': result.get('media_seconds', 0),
                                'download_seconds': result.get('download_seconds', 0),
                                'download_speed_mbps': result.get('download_speed_mbps', 0),
                                'bandwidth_basis': result.get('bandwidth_basis', ''),
                                'connection_latency_ms': connection_latency_ms,
                                'quality_score': quality_score,
                                'bandwidth_skipped': result.get('bandwidth_skipped', False),
                                'bandwidth_skip_reason': result.get('bandwidth_skip_reason', ''),
                                'sample_seconds': sample_seconds,
                                'min_sample_seconds': min_sample_seconds,
                                'sample_seconds_pass': sample_seconds_pass,
                                'ffmpeg_used': result.get('ffmpeg_used', True),
                                'ffmpeg_available': ffmpeg_available,
                                'ffmpeg_resolution_found': ffmpeg_resolution_found,
                                'ffmpeg_error': result.get('ffmpeg_error', ''),
                                'resolution_pass': resolution_pass,
                                'bandwidth_pass': bandwidth_pass,
                                'resolution_compensation_pass': resolution_compensation_pass}
            }
        except Exception as e:
            return {'index': idx, 'channel_info': channel_info, 'url': url, 'pass': False, 'reason': str(e),'duration': time.time() - start_time }

    # 开始计时
    start_time = time.time()

    def handle_channel_result(result):
        nonlocal processed

        processed += 1
        remaining = total - processed

        # 安全提取数据，防止 result 结构不对导致报错
        channel_info = result.get('channel_info', {})
        url = result.get('url', '')
        name = channel_info.get('name', '未知')
        cost_time = result.get('duration', 0)
        test_result = result.get('test_result') or {}
        resolution = test_result.get('resolution', 'N/A')
        bandwidth = test_result.get('bandwidth_MBps', test_result.get('speed_MBps', 0))
        connection_latency_ms = test_result.get('connection_latency_ms')
        quality_score = test_result.get('quality_score')
        if quality_score is None:
            quality_score = calculate_quality_score(bandwidth, connection_latency_ms)
        else:
            try:
                quality_score = float(quality_score)
            except (TypeError, ValueError):
                quality_score = calculate_quality_score(bandwidth, connection_latency_ms)
        codec = test_result.get('codec', '')
        is_h265 = test_result.get('is_h265', False)
        eff_min_bw = test_result.get('effective_min_bw', min_bw)
        eff_bw_comp = test_result.get('effective_bw_comp', bw_comp)
        codec_tag = ' [H.265]' if is_h265 else ''
        sample_seconds = (
            test_result.get('sample_seconds')
            or test_result.get('media_seconds')
            or test_result.get('measured_seconds')
            or 0
        )
        reason = ''

        if result.get('pass'):
            verdict = '通过'
            if test_result.get('resolution_compensation_pass'):
                reason = '未获取分辨率，带宽补偿通过'
            else:
                reason = '符合条件'
            filtered_list.append((channel_info, url))
            # 实时回调，立即写入结果文件
            if on_pass_callback:
                try:
                    on_pass_callback(name, {
                        'url': url,
                        'bandwidth_MBps': round(bandwidth, 2),
                        'connection_latency_ms': round(connection_latency_ms, 2) if connection_latency_ms is not None else None,
                        'quality_score': round(quality_score, 4),
                    })
                except Exception as e:
                    logger.warning(f"实时写入回调失败: {e}")

        else:
            if test_result:
                verdict = '拒绝'
                reasons = []
                resolution_found = test_result.get('ffmpeg_resolution_found', False)
                if test_result.get('low_resolution_url'):
                    reasons.append(f"URL标记低清晰度({test_result.get('low_resolution_hint')})")
                elif not test_result.get('resolution_pass'):
                    if not resolution_found:
                        ffmpeg_error = test_result.get('ffmpeg_error', '')
                        if not test_result.get('ffmpeg_available', True) and ffmpeg_error:
                            reasons.append(ffmpeg_error)
                        elif bandwidth >= eff_bw_comp and not test_result.get('sample_seconds_pass', True):
                            reasons.append(
                                f"未获取分辨率且有效采样不足({test_result.get('sample_seconds', 0):.2f}秒 "
                                f"< {test_result.get('min_sample_seconds', 0):.2f}秒)"
                            )
                        else:
                            reasons.append(f"未获取分辨率且带宽补偿不足{codec_tag}({bandwidth:.2f}MB/s < {eff_bw_comp}MB/s)")
                    else:
                        reasons.append(f"分辨率不足({test_result.get('resolution', 'N/A')})")
                if (
                    not test_result.get('bandwidth_pass')
                    and not test_result.get('low_resolution_url')
                    and not test_result.get('bandwidth_skipped')
                ):
                    reasons.append(f"带宽不足{codec_tag}({bandwidth:.2f}MB/s <= {eff_min_bw}MB/s)")
                if not reasons:
                    reasons.append(f"分辨率不足({test_result.get('resolution', 'N/A')})")
                reason = ', '.join(reasons)

            else:
                verdict = '错误'
                error_reason = result.get('reason', '未知错误')
                reason = error_reason

        # 收集结构化结果，供 Web 仪表盘使用
        test_results.append({
            'channel': name,
            'url': url,
            'resolution': resolution,
            'bandwidth_MBps': round(bandwidth, 2),
            'connection_latency_ms': round(connection_latency_ms, 2) if connection_latency_ms is not None else None,
            'quality_score': round(quality_score, 4),
            'codec': codec,
            'is_h265': is_h265,
            'sample_seconds': round(sample_seconds, 2),
            'passed': result.get('pass', False),
            'reason': reason,
            'cost_seconds': round(cost_time, 2)
        })

        status = f"{verdict} | 原因: {reason}"
        logger.info(
            "[%s/%s] %s | 频道: %s | 分辨率: %s | 带宽: %.2fMB/s%s | 延迟: %s | 评分: %.2f | 采样: %.2fs | 耗时: %.2fs | 原因: %s | URL: %s",
            processed,
            total,
            verdict,
            name,
            resolution,
            bandwidth,
            codec_tag,
            f"{connection_latency_ms:.0f}ms" if connection_latency_ms is not None else "-",
            quality_score,
            sample_seconds,
            cost_time,
            reason,
            url
        )

        if progress_callback:
            try:
                progress_callback({
                    'processed': processed,
                    'total': total,
                    'remaining': remaining,
                    'success': len(filtered_list),
                    'failed': processed - len(filtered_list),
                    'last_result': result,
                    'last_status': status,
                })
            except Exception as e:
                logger.warning(f"更新任务进度失败: {e}")

    executor = ThreadPoolExecutor(max_workers=max_workers)
    future_info = {}
    item_iter = iter(enumerate(iptv_list, 1))
    no_more_items = False

    def submit_next():
        if stop_event and stop_event.is_set():
            return None

        try:
            item = next(item_iter)
        except StopIteration:
            return None

        idx, (channel_info, url) = item
        info = {
            'index': idx,
            'channel_info': channel_info,
            'url': url,
            'start_time': None,
        }

        def run_channel():
            info['start_time'] = time.time()
            return test_single_channel(item)

        future = executor.submit(run_channel)
        future_info[future] = info
        return future

    def fill_pending_slots(pending):
        nonlocal no_more_items

        if no_more_items or (stop_event and stop_event.is_set()):
            return pending

        while len(pending) < max_workers:
            if download_limiter.should_pause():
                download_limiter.log_pause_if_needed(logger)
                break

            future = submit_next()
            if not future:
                no_more_items = True
                break

            pending.add(future)

            # 限流开启时按节奏补任务，让系统带宽采样有时间反映新增下载。
            if download_limiter.enabled:
                break

        return pending

    try:
        pending = set()
        pending = fill_pending_slots(pending)

        while pending or not no_more_items:
            if stop_event and stop_event.is_set():
                logger.info("收到终止请求，正在停止未完成任务")
                no_more_items = True
                for future in list(pending):
                    info = future_info.pop(future, None)
                    if info:
                        _reg_timeout(info['url'])
                    future.cancel()
                pending.clear()
                break

            if pending:
                done, pending = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
            else:
                time.sleep(0.5)
                done = set()

            for future in done:
                info = future_info.pop(future)
                try:
                    result = future.result()
                except Exception as e:
                    started_at = info['start_time'] or time.time()
                    result = {
                        'index': info['index'],
                        'channel_info': info['channel_info'],
                        'url': info['url'],
                        'pass': False,
                        'reason': str(e),
                        'duration': time.time() - started_at
                    }
                handle_channel_result(result)

            now = time.time()
            timed_out = []
            for future in list(pending):
                info = future_info[future]
                if info['start_time'] is None:
                    continue

                elapsed = now - info['start_time']
                if elapsed >= channel_timeout:
                    timed_out.append((future, info, elapsed))

            for future, info, elapsed in timed_out:
                future.cancel()
                pending.remove(future)
                future_info.pop(future, None)
                url = info['url']
                # 通知 FFmpegTest 主动中断流读取，释放连接
                _reg_timeout(url)
                timeout_result = {
                    'index': info['index'],
                    'channel_info': info['channel_info'],
                    'url': url,
                    'pass': False,
                    'reason': f'单频道测试超时({channel_timeout}秒)',
                    'duration': elapsed
                }
                handle_channel_result(timeout_result)

            pending = fill_pending_slots(pending)
    finally:
        # 不等待残留线程：主循环已通过 channel_timeout 标记并收集了所有结果，
        # 残留线程仅剩网络/FFmpeg 清理，无需阻塞主线程。
        executor.shutdown(wait=False, cancel_futures=True)

    # 任务结束日志
    total_elapsed = time.time() - start_time
    logger.info(f"任务完成 | 符合条件: {len(filtered_list)} | 耗时: {total_elapsed:.2f}秒")

    return filtered_list, test_results

def load_subscribe_urls():
    """从数据库读取订阅源地址，每行一个，忽略空行和 # 注释行。"""
    from db import get_config_data
    content = get_config_data('subscribe')
    urls = []
    for line in content.split('\n'):
        line = line.strip()
        if line and not line.startswith('#'):
            urls.append(line)
    return urls


def load_aliases():
    """
    从数据库读取频道别名，返回 (canonical_to_aliases, name_to_canonical, regex_aliases)。
    canonical_to_aliases: {主名: [别名列表]}
    name_to_canonical:    {频道名(精确): 主名}
    regex_aliases:        [(compiled_regex, 主名), ...]
    """
    from db import get_config_data
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
    return canonical_to_aliases, name_to_canonical, regex_aliases


def match_channel_name(name, name_to_canonical, regex_aliases=None):
    """根据别名表匹配频道名称，返回主名；无匹配返回 None。"""
    if not name:
        return None
    # 精确匹配（O(1)）
    if name in name_to_canonical:
        return name_to_canonical[name]
    # 正则匹配（预编译，比逐条快很多）
    if regex_aliases:
        for pattern, canonical in regex_aliases:
            if pattern.match(name):
                return canonical
    return None


def parse_demo_file():
    """从数据库读取 demo 模板，返回 [(genre, [channel_name, ...]), ...]。"""
    from db import get_config_data
    content = get_config_data('demo')
    structure = []
    current_genre = None
    current_channels = []
    for line in content.split('\n'):
        line = line.strip()
        if not line:
            continue
        if ',#genre#' in line:
            if current_genre is not None:
                structure.append((current_genre, current_channels))
            current_genre = line.split(',')[0]
            current_channels = []
        else:
            current_channels.append(line)
    if current_genre is not None:
        structure.append((current_genre, current_channels))
    return structure


def match_channels_from_m3u(iptv_list, demo_structure, name_to_canonical, regex_aliases=None):
    """
    从 M3U 列表中找到 demo 需要的频道对应的 URL。
    返回 {主名: [url1, url2, ...]}。
    """
    # 收集 demo 中所有需要的频道主名
    needed = set()
    for _, channels in demo_structure:
        for ch in channels:
            matched = match_channel_name(ch, name_to_canonical, regex_aliases)
            needed.add(matched if matched else ch)

    matched = {}
    for channel_info, url in iptv_list:
        raw_name = channel_info.get('name', '')
        canonical = match_channel_name(raw_name, name_to_canonical, regex_aliases) or raw_name
        if canonical in needed:
            if canonical not in matched:
                matched[canonical] = []
            if url not in matched[canonical]:
                matched[canonical].append(url)
    return matched


def _resolve_urls(ch, filtered_urls, name_to_canonical, regex_aliases=None):
    """查找频道对应的通过测速的 URL 列表，支持别名解析。"""
    urls = filtered_urls.get(ch, [])
    if not urls and name_to_canonical:
        canonical = match_channel_name(ch, name_to_canonical, regex_aliases)
        if canonical and canonical != ch:
            urls = filtered_urls.get(canonical, [])
    return [_entry_url(item) for item in urls]


def save_result_txt(demo_structure, filtered_urls, name_to_canonical=None, regex_aliases=None, output_file='result.txt', show_update_time=True, update_time_position='top'):
    """按 demo 格式输出结果到 txt 文件。只输出测速通过的频道，跳过空分类。"""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    update_block = f'🕘️更新时间,#genre#\n{now_str},邮箱联系\n\n'

    with open(output_file, 'w', encoding='utf-8') as f:
        if show_update_time and update_time_position == 'top':
            f.write(update_block)

        for genre, channels in demo_structure:
            genre_lines = []
            for ch in channels:
                urls = _resolve_urls(ch, filtered_urls, name_to_canonical, regex_aliases)
                for url in urls:
                    genre_lines.append(f'{ch},{url}\n')
            if genre_lines:
                f.write(f'{genre},#genre#\n')
                for line in genre_lines:
                    f.write(line)
                f.write('\n')

        if show_update_time and update_time_position == 'bottom':
            f.write(update_block)


def save_result_m3u(demo_structure, filtered_urls, name_to_canonical=None, regex_aliases=None, output_file='result.m3u', show_update_time=True, update_time_position='top'):
    """输出 M3U 格式文件。只输出测速通过的频道，跳过空分类。"""
    logo_base = 'https://www.xn--rgv465a.top/tvlogo'
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    update_entry = (
        f'#EXTINF:-1 tvg-id="更新时间" tvg-name="更新时间" '
        f'group-title="🕘️更新时间",{now_str}\n'
        f'http://localhost/update_time\n'
    )

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('#EXTM3U x-tvg-url="http://192.168.3.61:8080/epg/epg.gz"\n')

        if show_update_time and update_time_position == 'top':
            f.write(update_entry)

        for genre, channels in demo_structure:
            genre_lines = []
            for ch in channels:
                urls = _resolve_urls(ch, filtered_urls, name_to_canonical, regex_aliases)
                for url in urls:
                    genre_lines.append(
                        f'#EXTINF:-1 tvg-id="{ch}" tvg-name="{ch}" '
                        f'tvg-logo="{logo_base}/{ch}.png" '
                        f'group-title="{genre}",{ch}\n'
                        f'{url}\n'
                    )
            if genre_lines:
                for line in genre_lines:
                    f.write(line)

        if show_update_time and update_time_position == 'bottom':
            f.write(update_entry)


def save_run_result(run_data, filepath='output/history.json'):
    """将本轮测速结果写入 SQLite 数据库。"""
    insert_run(run_data)


def run_test_cycle(progress_callback=None, log_callback=None, stop_event=None):
    """执行一轮完整的测速筛选流程。每次运行时重新读取所有配置。"""
    from db import clear_run_progress, update_run_progress
    _clear_timeouts()
    run_start_time = time.time()
    run_id = now_str().replace('-', '').replace(':', '').replace(' ', '_')

    # 清空旧进度，标记新运行开始
    clear_run_progress()

    def _log(msg):
        # 始终写入数据库
        try:
            from db import insert_log as _db_insert_log
            _db_insert_log(run_id, 'INFO', msg)
        except Exception:
            pass
        if log_callback:
            try:
                log_callback(msg)
            except Exception:
                pass

    cfg = load_config()
    _, name_to_canonical, regex_aliases = load_aliases()
    demo_structure = parse_demo_file()

    if not demo_structure:
        print("demo 模板为空，跳过")
        _log("频道模板为空，请先配置频道模板")
        return

    TEST_DURATION = cfg['test_duration']
    MAX_WORKERS = cfg['max_workers']
    try:
        MAX_URLS_PER_CHANNEL = max(0, int(cfg.get('max_urls_per_channel', 0) or 0))
    except (TypeError, ValueError):
        MAX_URLS_PER_CHANNEL = 0

    # 获取订阅源
    m3u_urls = load_subscribe_urls()

    if not m3u_urls:
        print("订阅源为空，请在 Web 后台「系统配置」中填写订阅源地址")
        _log("订阅源为空，请先配置订阅源地址")
        return

    _log(f"开始测试任务，共 {len(m3u_urls)} 个数据源")
    print(f"数据源数量：{len(m3u_urls)}")
    print(f"测试时长：{TEST_DURATION}秒/频道 | 并发线程：{MAX_WORKERS}")
    print(f"最低分辨率：{cfg['min_width']}x{cfg['min_height']} | 最低带宽：{cfg['min_bandwidth_MBps']}MB/s")
    print(f"系统限速：{cfg['system_bandwidth_limit_MBps']}MB/s")
    print(f"每频道输出数量：{MAX_URLS_PER_CHANNEL if MAX_URLS_PER_CHANNEL > 0 else '不限制'}")
    print("=" * 60)

    # 获取并解析所有 M3U 数据源
    all_iptv_list = []
    for idx, m3u_url in enumerate(m3u_urls, 1):
        _log(f"[{idx}/{len(m3u_urls)}] 正在获取: {m3u_url}")
        print(f"\n[{idx}/{len(m3u_urls)}] 正在从 {m3u_url} 获取 M3U 数据...")
        m3u_content = fetch_m3u_playlist(m3u_url)
        if m3u_content:
            iptv_list = parse_iptv_addresses(m3u_content)
            _log(f"  -> 解析到 {len(iptv_list)} 个频道地址")
            print(f"  -> 解析到 {len(iptv_list)} 个频道地址")
            all_iptv_list.extend(iptv_list)
        else:
            _log(f"  -> 获取失败，跳过")
            print("  -> 获取失败，跳过")

    print(f"\n共计解析 {len(all_iptv_list)} 个频道地址")

    # 匹配 demo 中的频道
    matched_urls = match_channels_from_m3u(all_iptv_list, demo_structure, name_to_canonical, regex_aliases)
    matched_count = sum(len(v) for v in matched_urls.values())
    _log(f"匹配到 {len(matched_urls)} 个频道，共 {matched_count} 个待测地址")
    print(f"匹配到 demo 中 {len(matched_urls)} 个频道，共 {matched_count} 个地址")

    # 构建待测列表
    test_list = []
    for canonical_name, urls in matched_urls.items():
        for url in urls:
            test_list.append(({'name': canonical_name}, url))

    print(f"待测频道数：{len(test_list)}\n")
    _log(f"开始测速，共 {len(test_list)} 个频道地址")

    if not test_list:
        print("没有可测试的频道地址")
        _log("没有可测试的频道地址")
        return

    # 确保输出目录存在
    output_dir = os.path.dirname(cfg['output_txt'])
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    # 实时写入的频道通过记录
    filtered_urls = {}
    _write_lock = threading.Lock()
    show_time = cfg.get('show_update_time', True)
    time_pos = cfg.get('update_time_position', 'top')
    save_result_txt(demo_structure, filtered_urls, name_to_canonical, regex_aliases, cfg['output_txt'], show_time, time_pos)
    save_result_m3u(demo_structure, filtered_urls, name_to_canonical, regex_aliases, cfg['output_m3u'], show_time, time_pos)
    _log("已清空旧输出文件，开始写入本轮实时结果")

    def _on_channel_pass(name, entry):
        """频道通过测速时立即追加并重写结果文件。"""
        url = _entry_url(entry)
        with _write_lock:
            if name not in filtered_urls:
                filtered_urls[name] = []
            if url and url not in {_entry_url(item) for item in filtered_urls[name]}:
                filtered_urls[name].append(entry)
            filtered_urls[name] = sort_and_limit_channel_entries(filtered_urls[name], MAX_URLS_PER_CHANNEL)
            save_result_txt(demo_structure, filtered_urls, name_to_canonical, regex_aliases, cfg['output_txt'], show_time, time_pos)
            save_result_m3u(demo_structure, filtered_urls, name_to_canonical, regex_aliases, cfg['output_m3u'], show_time, time_pos)

    # 测速筛选（实时写入）
    # 始终写入 SQLite 进度表，供 Web 端读取
    def _db_progress(info):
        update_run_progress(
            total=info.get('total', 0),
            processed=info.get('processed', 0),
            passed=info.get('success', 0),
            failed=info.get('failed', 0),
            elapsed=round(time.time() - run_start_time, 1),
            source='web' if progress_callback else 'scheduler',
        )

    def _combined_progress(info):
        _db_progress(info)
        if progress_callback:
            try:
                progress_callback(info)
            except Exception:
                pass

    _, test_results = filter_and_save_playlist(
        test_list,
        duration=TEST_DURATION,
        max_workers=MAX_WORKERS,
        config=cfg,
        progress_callback=_combined_progress,
        on_pass_callback=_on_channel_pass,
        run_id=run_id,
        stop_event=stop_event
    )

    filtered_urls = build_output_urls_from_results(test_results, MAX_URLS_PER_CHANNEL)
    save_result_txt(demo_structure, filtered_urls, name_to_canonical, regex_aliases, cfg['output_txt'], show_time, time_pos)
    save_result_m3u(demo_structure, filtered_urls, name_to_canonical, regex_aliases, cfg['output_m3u'], show_time, time_pos)

    # 运行结束，清空进度
    clear_run_progress()

    # 汇总并保存结构化结果
    run_elapsed = time.time() - run_start_time
    passed_urls = sum(1 for r in test_results if r['passed'])
    output_urls = sum(len(v) for v in filtered_urls.values())
    total_tested = len(test_results)
    all_channels = {r['channel'] for r in test_results}
    passed_channels = {r['channel'] for r in test_results if r['passed']}
    passed_count = len(passed_channels)

    run_data = {
        'run_id': run_id,
        'started_at': timestamp_str(run_start_time),
        'finished_at': now_str(),
        'duration_seconds': round(run_elapsed, 1),
        'summary': {
            'total_tested': total_tested,
            'total_passed': passed_urls,
            'total_failed': total_tested - passed_urls,
            'pass_rate': round(passed_urls / total_tested * 100, 1) if total_tested else 0,
            'unique_channels_passed': len(passed_channels),
            'unique_channels_total': len(all_channels)
        },
        'results': test_results
    }
    history_path = os.path.join(os.path.dirname(cfg['output_txt']) or '.', 'history.json')
    save_run_result(run_data, history_path)

    print(f"\n{'=' * 60}")
    print(f"完成！通过 {passed_count} 个频道（{passed_urls} 个地址），输出 {output_urls} 个地址")
    print(f"结果已保存到 {cfg['output_txt']} 和 {cfg['output_m3u']}")
    print(f"历史记录已保存到 {history_path}")
    print(f"{'=' * 60}")
    _log(f"测试完成！通过 {passed_count} 个频道（{passed_urls} 个地址），输出 {output_urls} 个地址，耗时 {run_elapsed:.0f} 秒")


def _next_run_datetime(run_mode, run_times, run_interval_minutes):
    """计算下一次运行的绝对时间，返回 datetime 对象。"""
    now = datetime.now()
    if run_mode == 'times' and run_times:
        today = now.date()
        candidates = []
        for t_str in run_times:
            try:
                t = datetime.strptime(t_str, "%H:%M").time()
                target = datetime.combine(today, t)
                if target <= now:
                    target = target + timedelta(days=1)
                candidates.append(target)
            except ValueError:
                continue
        return min(candidates) if candidates else None
    elif run_mode == 'interval' and run_interval_minutes > 0:
        return now + timedelta(minutes=run_interval_minutes)
    return None


if __name__ == "__main__":
    cfg = load_config()
    run_mode = cfg.get('run_mode', 'once')

    print("=" * 60)
    print("IPTV 频道质量筛选工具 v3.0")
    print("=" * 60)

    # 初始化数据库，迁移旧数据
    init_db()
    migrated = migrate_from_json()
    if migrated > 0:
        print(f"已从 history.json 迁移 {migrated} 轮历史数据到 SQLite")

    if not load_subscribe_urls():
        print("订阅源为空，请先运行 python web.py 在后台配置订阅源")
    elif run_mode == 'once':
        run_test_cycle()

    else:
        cfg = load_config()
        label = f"指定时间 {cfg['run_times']}" if run_mode == 'times' else f"每 {cfg['run_interval_minutes']} 分钟"
        print(f"循环模式：{label}，Ctrl+C 退出")
        print("=" * 60)
        try:
            while True:
                cfg = load_config()
                next_run = _next_run_datetime(run_mode, cfg.get('run_times', []), cfg.get('run_interval_minutes', 0))
                if next_run is None:
                    print("无法计算下次执行时间，退出")
                    break
                wait_sec = (next_run - datetime.now()).total_seconds()
                if wait_sec > 0:
                    print(f"\n下次执行：{next_run.strftime('%Y-%m-%d %H:%M:%S')}（{wait_sec/60:.1f} 分钟后）")
                    time.sleep(wait_sec)

                print(f"\n{'#' * 60}")
                print(f"定时任务触发：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"{'#' * 60}")

                try:
                    run_test_cycle()
                except Exception as e:
                    print(f"\n本轮执行异常：{e}")
                    print("继续等待下一轮...")
        except KeyboardInterrupt:
            print("\n用户中断，退出")

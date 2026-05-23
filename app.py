import time
import requests
import re
import logging
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from requests.exceptions import SSLError
from FFmpegTest import analyze_iptv_with_ffmpeg

try:
    import psutil
except ImportError:
    psutil = None


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
        self.current_mbps = (byte_delta * 8) / (elapsed * 1_000_000)
        self._last_bytes = bytes_recv
        self._last_time = now
        return self.current_mbps

    def should_pause(self):
        return self.enabled and self.refresh() >= self.limit_mbps

    def log_pause_if_needed(self, logger):
        now = time.monotonic()
        if now - self._last_log_time >= self.log_interval:
            logger.info(
                "总下行 %.2fMb/s >= %.2fMb/s，暂停启动新频道",
                self.current_mbps,
                self.limit_mbps
            )
            self._last_log_time = now


# --- 日志配置模块 ---
def setup_logging():
    """配置日志系统，创建 logs 目录并生成时间命名的日志文件"""
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # --- 关键修正 1：获取 Root Logger 并移除旧 Handlers ---
    # 这样可以防止重复添加处理器
    root_logger = logging.getLogger()
    if root_logger.handlers:
        # 清理旧的 handlers，防止文件句柄泄露
        for handler in root_logger.handlers[:]:
            handler.close()
            root_logger.removeHandler(handler)

    # 生成日志文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f"{timestamp}.log")

    # --- 关键修正 2：使用 filemode='w' 覆盖旧配置 ---
    # 因为我们手动清理了 handlers，basicConfig 会重新生效
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8', mode='w'),  # mode='w' 确保是新文件
            logging.StreamHandler()
        ]
    )

    logger = logging.getLogger(__name__)
    logger.info(f"日志系统已启动，日志文件: {log_file}")
    return logger


# 全局 logger 变量
# logger = setup_logging()

def fetch_m3u_playlist(url):
    """
    从指定 URL 获取 M3U 播放列表数据
    :param url: M3U 数据的 URL
    :return: str M3U 内容
    """
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.text
    except SSLError:
        response = requests.get(url, timeout=10, verify=False)
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


def test_iptv_quality(url, duration=10):
    """
    测试 IPTV 流的质量（分辨率和带宽）
    :param url: IPTV 地址
    :param duration: 采样时长（秒）
    :return: dict 包含测试结果
    """
    low_resolution_hint = detect_low_resolution_url(url)
    if low_resolution_hint:
        return {
            'pass': False,
            'resolution': f"URL标记:{low_resolution_hint}",
            'speed_mbps': 0,
            'bandwidth_mbps': 0,
            'bitrate_mbps': 0,
            'resolution_pass': False,
            'bandwidth_pass': False,
            'low_resolution_url': True,
            'low_resolution_hint': low_resolution_hint,
            'resolution_compensation_pass': False
        }

    result = analyze_iptv_with_ffmpeg(url, duration)
    
    if not result or not result.get('success'):
        return {'pass': False, 'reason': '分析失败'}
    
    width = result.get('width', 0)
    height = result.get('height', 0)
    bandwidth_mbps = result.get('bandwidth_mbps', result.get('speed_mbps', 0))
    ffmpeg_available = result.get('ffmpeg_available', True)
    ffmpeg_resolution_found = result.get('ffmpeg_resolution_found', width > 0 and height > 0)
    sample_seconds, min_sample_seconds, sample_seconds_pass = get_bandwidth_sample_info(result, duration)
    
    # 判断分辨率是否 >= 1080P (1920x1080)
    resolution_pass = (width >= 1920 and height >= 1080)
    
    # 判断连接成功后的平均带宽是否 > 1Mb/s
    bandwidth_pass = bandwidth_mbps > 1.0
    resolution_compensation_pass = (
        ffmpeg_available
        and (not ffmpeg_resolution_found)
        and bandwidth_mbps >= 2.0
        and sample_seconds_pass
    )
    
    passed = (resolution_pass and bandwidth_pass) or resolution_compensation_pass
    
    return {
        'pass': passed,
        'resolution': f"{width}x{height}",
        'speed_mbps': bandwidth_mbps,
        'bandwidth_mbps': bandwidth_mbps,
        'bitrate_mbps': result.get('bitrate_mbps', bandwidth_mbps),
        'ffmpeg_available': ffmpeg_available,
        'bandwidth_skipped': result.get('bandwidth_skipped', False),
        'bandwidth_skip_reason': result.get('bandwidth_skip_reason', ''),
        'sample_seconds': sample_seconds,
        'min_sample_seconds': min_sample_seconds,
        'sample_seconds_pass': sample_seconds_pass,
        'resolution_pass': resolution_pass,
        'bandwidth_pass': bandwidth_pass,
        'resolution_compensation_pass': resolution_compensation_pass
    }

def filter_and_save_playlist(
    iptv_list,
    output_file='list.m3u',
    duration=10,
    max_workers=5,
    progress_callback=None,
    bandwidth_limit_mbps=50
):
    """
    过滤并保存符合条件的 IPTV 列表（修改版：增加详细日志和进度计算）
    """
    global logger
    filtered_list = []
    total = len(iptv_list)
    processed = 0
    failed = 0

    # 重新初始化 logger 以确保每次任务都有新文件（可选，取决于你的部署方式）
    # 如果是 Flask 多次调用，建议在 generate_playlist 里调用 setup_logging
    logger = setup_logging()

    logger.info(f"开始测试任务")
    logger.info(f"总频道数: {total}")
    logger.info(f"并发线程数: {max_workers}")
    logger.info(f"单个频道测试时长: {duration}秒")
    channel_timeout = max(duration + 15, int(duration * 1.5))
    logger.info(f"单频道最大等待时间: {channel_timeout}秒")
    download_limiter = SystemDownloadLimiter(bandwidth_limit_mbps)
    if download_limiter.enabled:
        logger.info(f"总下行启动限速: {download_limiter.limit_mbps:.2f}Mb/s")
    elif bandwidth_limit_mbps and psutil is None:
        logger.info("总下行启动限速: 未安装 psutil，已关闭")
    else:
        logger.info("总下行启动限速: 已关闭")

    def test_single_channel(args):
        """单个频道测试函数"""
        idx, (channel_info, url) = args
        start_time = time.time()  # 记录开始时间

        try:
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
                        'speed_mbps': 0,
                        'bandwidth_mbps': 0,
                        'bitrate_mbps': 0,
                        'speed_MBps': 0,
                        'measured_seconds': 0,
                        'ffmpeg_used': False,
                        'ffmpeg_available': True,
                        'ffmpeg_resolution_found': False,
                        'ffmpeg_error': '',
                        'low_resolution_url': True,
                        'low_resolution_hint': low_resolution_hint,
                        'resolution_pass': False,
                        'bandwidth_pass': False,
                        'resolution_compensation_pass': False
                    }
                }

            result = analyze_iptv_with_ffmpeg(url, duration)
            if not result or not result.get('success'):
                error_reason = result.get('error', '分析失败') if result else '分析失败'
                return {'index': idx, 'channel_info': channel_info, 'url': url, 'pass': False, 'reason': error_reason,'duration': time.time() - start_time }

            width = result.get('width', 0)
            height = result.get('height', 0)
            bandwidth_mbps = result.get('bandwidth_mbps', result.get('speed_mbps', 0))
            ffmpeg_available = result.get('ffmpeg_available', True)
            ffmpeg_resolution_found = result.get('ffmpeg_resolution_found', width > 0 and height > 0)
            sample_seconds, min_sample_seconds, sample_seconds_pass = get_bandwidth_sample_info(result, duration)

            resolution_pass = (width >= 1920 and height >= 1080)
            bandwidth_pass = bandwidth_mbps > 1.0
            resolution_compensation_pass = (
                ffmpeg_available
                and (not ffmpeg_resolution_found)
                and bandwidth_mbps >= 2.0
                and sample_seconds_pass
            )
            passed = (resolution_pass and bandwidth_pass) or resolution_compensation_pass

            return {
                'index': idx, 'channel_info': channel_info, 'url': url, 'pass': passed,'duration': time.time() - start_time ,
                'test_result': {'resolution': f"{width}x{height}", 'speed_mbps': bandwidth_mbps,
                                'bandwidth_mbps': bandwidth_mbps,
                                'bitrate_mbps': result.get('bitrate_mbps', bandwidth_mbps),
                                'speed_MBps': result.get('speed_MBps', 0),
                                'measured_seconds': result.get('measured_seconds', 0),
                                'media_seconds': result.get('media_seconds', 0),
                                'download_seconds': result.get('download_seconds', 0),
                                'download_speed_mbps': result.get('download_speed_mbps', 0),
                                'bandwidth_basis': result.get('bandwidth_basis', ''),
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
        bandwidth = test_result.get('bandwidth_mbps', test_result.get('speed_mbps', 0))
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
                        elif bandwidth >= 2.0 and not test_result.get('sample_seconds_pass', True):
                            reasons.append(
                                f"未获取分辨率且有效采样不足({test_result.get('sample_seconds', 0):.2f}秒 "
                                f"< {test_result.get('min_sample_seconds', 0):.2f}秒)"
                            )
                        else:
                            reasons.append(f"未获取分辨率且带宽补偿不足({bandwidth:.2f}Mb/s < 2Mb/s)")
                    else:
                        reasons.append(f"分辨率不足({test_result.get('resolution', 'N/A')})")
                if (
                    not test_result.get('bandwidth_pass')
                    and not test_result.get('low_resolution_url')
                    and not test_result.get('bandwidth_skipped')
                ):
                    reasons.append(f"带宽不足({bandwidth:.2f}Mb/s <= 1Mb/s)")
                if not reasons:
                    reasons.append(f"分辨率不足({test_result.get('resolution', 'N/A')})")
                reason = ', '.join(reasons)

            else:
                verdict = '错误'
                error_reason = result.get('reason', '未知错误')
                reason = error_reason

        status = f"{verdict} | 原因: {reason}"
        logger.info(
            "[%s/%s] %s | 频道: %s | 分辨率: %s | 带宽: %.2fMb/s | 采样: %.2fs | 耗时: %.2fs | 原因: %s | URL: %s",
            processed,
            total,
            verdict,
            name,
            resolution,
            bandwidth,
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

        if no_more_items:
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
                timeout_result = {
                    'index': info['index'],
                    'channel_info': info['channel_info'],
                    'url': info['url'],
                    'pass': False,
                    'reason': f'单频道测试超时({channel_timeout}秒)',
                    'duration': elapsed
                }
                handle_channel_result(timeout_result)

            pending = fill_pending_slots(pending)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    # 任务结束日志
    total_elapsed = time.time() - start_time
    logger.info(f"任务完成 | 符合条件: {len(filtered_list)} | 耗时: {total_elapsed:.2f}秒")

    # 保存结果
    save_to_m3u(filtered_list, output_file)
    return filtered_list  # 确保返回结果

def save_to_m3u(iptv_list, output_file):
    """
    将 IPTV 列表保存为 M3U 格式
    :param iptv_list: IPTV 列表
    :param output_file: 输出文件名
    """
    with open(output_file, 'w', encoding='utf-8') as f:
        # 写入文件头
        f.write('#EXTM3U x-tvg-url="https://live.fanmingming.cn/e.xml"\n')
        
        # 写入频道信息
        for channel_info, url in iptv_list:
            group = channel_info.get('group', '')
            name = channel_info.get('name', '')
            
            if group:
                f.write(f'#EXTINF:-1 group-title="{group}",{name}\n')
            else:
                f.write(f'#EXTINF:-1,{name}\n')
            
            f.write(f'{url}\n')


if __name__ == "__main__":
    # M3U 数据源 URL
    m3u_url = "https://gh-proxy.com/https://raw.githubusercontent.com/Guovin/iptv-api/gd/output/result.m3u"
    
    # 配置参数
    TEST_DURATION = 15      # 每个频道测试时长（秒）
    MAX_WORKERS = 30         # 最大并发线程数
    OUTPUT_FILE = 'list.m3u'  # 输出文件名
    
    print("="*60)
    print("IPTV 频道质量筛选工具 v2.0")
    print("="*60)
    print(f"数据源：{m3u_url}")
    print(f"测试时长：{TEST_DURATION}秒/频道")
    print(f"并发线程：{MAX_WORKERS}")
    print(f"输出文件：{OUTPUT_FILE}")
    print("="*60)
    
    # 获取 M3U 数据
    print(f"正在从 {m3u_url} 获取 M3U 数据...")
    m3u_content = fetch_m3u_playlist(m3u_url)
    
    if m3u_content:
        # 解析 IPTV 地址
        iptv_list = parse_iptv_addresses(m3u_content)
        print(f"成功解析 {len(iptv_list)} 个 IPTV 组播地址")
        
        if len(iptv_list) > 0:
            # 过滤并保存（采样时长 30 秒，多线程加速）
            filter_and_save_playlist(
                iptv_list, 
                output_file=OUTPUT_FILE, 
                duration=TEST_DURATION,
                max_workers=MAX_WORKERS
            )
        else:
            print("错误：未解析到任何 IPTV 地址")
    else:
        print("错误：无法获取 M3U 数据")

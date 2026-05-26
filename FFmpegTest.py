import os
import re
import shutil
import subprocess
import time
from urllib.parse import urljoin

import requests
import urllib3
from requests.exceptions import SSLError


# 超时 URL 注册表，供流读取循环主动退出并释放连接
_timed_out_urls = set()


def register_timeout(url):
    """将 URL 标记为超时，正在进行的流读取会尽快退出。"""
    _timed_out_urls.add(url)


def clear_timeouts():
    """清除上一轮的超时标记，在新一轮测试开始前调用。"""
    _timed_out_urls.clear()


def _is_timed_out(url):
    """检查 URL 是否已被标记为超时。"""
    return url in _timed_out_urls


def request_timeout(deadline, connect_timeout=3, read_timeout=3):
    """根据单频道截止时间动态收紧 requests 超时。"""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("单频道测试超时")

    timeout = max(0.5, remaining)
    return min(connect_timeout, timeout), min(read_timeout, timeout)


DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Connection': 'close',
}
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
FFMPEG_BIN = os.environ.get('FFMPEG_BIN', 'ffmpeg')


def build_bandwidth_result(width, height, total_bytes, elapsed_seconds, basis='wall_clock_after_connect', connection_latency_ms=None):
    """根据连接成功后的读取耗时计算带宽，单位以 Mb/s 为准。"""
    if total_bytes <= 0:
        elapsed_seconds = max(elapsed_seconds, 0.001)
        speed_MBps = 0
        bandwidth_mbps = 0
    else:
        elapsed_seconds = max(elapsed_seconds, 0.001)
        speed_MBps = (total_bytes / (1024 * 1024)) / elapsed_seconds
        bandwidth_mbps = speed_MBps * 8

    rounded_bandwidth = round(bandwidth_mbps, 2)
    return {
        'width': width,
        'height': height,
        'resolution': f"{width}x{height}",
        'bandwidth_mbps': rounded_bandwidth,
        'bitrate_mbps': rounded_bandwidth,
        'speed_mbps': rounded_bandwidth,
        'speed_MBps': round(speed_MBps, 2),
        'measured_seconds': round(elapsed_seconds, 2),
        'total_bytes': total_bytes,
        'bandwidth_basis': basis,
        'connection_latency_ms': round(connection_latency_ms, 2) if connection_latency_ms is not None else None,
        'success': True
    }


def http_get(url, timeout, stream=False):
    """统一请求入口：补浏览器请求头，并在证书异常时回退到 verify=False。"""
    try:
        return requests.get(url, timeout=timeout, stream=stream, headers=DEFAULT_HEADERS, allow_redirects=True)
    except SSLError:
        return requests.get(
            url,
            timeout=timeout,
            stream=stream,
            headers=DEFAULT_HEADERS,
            allow_redirects=True,
            verify=False
        )


def is_hls_response(response, text_probe=''):
    """根据响应头、最终 URL 和内容片段判断是否为 HLS 播放列表。"""
    content_type = (response.headers.get('content-type') or '').lower()
    final_url = (response.url or '').lower()
    probe = (text_probe or '').lstrip()
    return (
        '.m3u8' in final_url
        or 'mpegurl' in content_type
        or probe.startswith('#EXTM3U')
    )


def probe_hls_url(url, deadline):
    """对无后缀或中转地址做一次轻量探测，识别是否实际返回 HLS 播放列表。"""
    try:
        with http_get(url, timeout=request_timeout(deadline, 3, 3), stream=False) as response:
            response.raise_for_status()
            text_probe = response.text[:4096]
            if is_hls_response(response, text_probe):
                return response.url
    except Exception:
        return None

    return None


def ffmpeg_test(url):
    """强制使用 FFmpeg 获取视频分辨率。"""
    if not shutil.which(FFMPEG_BIN):
        return {
            'success': False,
            'width': 0,
            'height': 0,
            'ffmpeg_available': False,
            'error': f'FFmpeg 不可用: 未找到 {FFMPEG_BIN}'
        }

    cmd = [
        FFMPEG_BIN,
        '-hide_banner',
        '-rw_timeout', '5000000',
        '-probesize', '512000',
        '-analyzeduration', '2000000',
        '-fflags', '+nobuffer',
        '-flags', 'low_delay',
        '-user_agent', DEFAULT_HEADERS['User-Agent'],
        '-i', url,
        '-t', '3',
        '-f', 'null',
        '-'
    ]

    try:
        completed = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='ignore',
            timeout=5
        )
        stderr_output = completed.stderr
    except subprocess.TimeoutExpired as e:
        stderr_output = e.stderr or ''
    except Exception as e:
        return {'success': False, 'width': 0, 'height': 0, 'error': f"FFmpeg 启动失败: {e}"}

    if isinstance(stderr_output, bytes):
        stderr_output = stderr_output.decode('utf-8', errors='ignore')

    resolution_match = re.search(r'(\d{3,5})x(\d{3,5})', stderr_output)

    # 提取视频编码格式：匹配 "Video: h264" / "Video: hevc" 等
    codec = ''
    codec_match = re.search(r'Video:\s*(\w+)', stderr_output, re.IGNORECASE)
    if codec_match:
        codec = codec_match.group(1).lower()

    if resolution_match:
        return {
            'success': True,
            'width': int(resolution_match.group(1)),
            'height': int(resolution_match.group(2)),
            'codec': codec,
            'ffmpeg_available': True,
            'error': ''
        }

    return {
        'success': False,
        'width': 0,
        'height': 0,
        'codec': codec,
        'ffmpeg_available': True,
        'error': 'FFmpeg 未解析到分辨率'
    }


def analyze_iptv_with_ffmpeg(url, duration=10, useffmpeg=True, min_width=1920, min_height=1080):
    """分析入口：强制使用 FFmpeg 做分辨率探测，再做带宽测试。"""
    try:
        deadline = time.monotonic() + max(duration, 1) + 8
        stream_url = url
        stream_kind = 'direct'

        if '.m3u8' in url:
            stream_kind = 'hls'
        elif '/rtp/' in url or '239.' in url:
            stream_kind = 'direct'
        else:
            probed_hls_url = probe_hls_url(url, deadline)
            if probed_hls_url:
                stream_url = probed_hls_url
                stream_kind = 'hls'

        width, height = 0, 0
        codec = ''
        ffmpeg_error = ''
        ffmpeg_available = True
        ffmpeg_resolution_found = False
        if useffmpeg:
            ffmpeg_result = ffmpeg_test(stream_url)
            ffmpeg_available = ffmpeg_result.get('ffmpeg_available', True)
            codec = ffmpeg_result.get('codec', '')
            if ffmpeg_result.get('success'):
                width = ffmpeg_result.get('width', 0)
                height = ffmpeg_result.get('height', 0)
                ffmpeg_resolution_found = width > 0 and height > 0
                if ffmpeg_resolution_found and (width < min_width or height < min_height):
                    result = build_bandwidth_result(width, height, 0, 0, basis='skipped_low_resolution')
                    result['ffmpeg_used'] = bool(useffmpeg)
                    result['ffmpeg_available'] = ffmpeg_available
                    result['ffmpeg_resolution_found'] = True
                    result['ffmpeg_error'] = ''
                    result['codec'] = codec
                    result['bandwidth_skipped'] = True
                    result['bandwidth_skip_reason'] = f'分辨率不足({width}x{height})，跳过测速'
                    return result
            else:
                ffmpeg_error = ffmpeg_result.get('error', 'FFmpeg 分析失败')

        if stream_kind == 'hls':
            result = test_hls_bandwidth(stream_url, width, height, duration)
        else:
            result = test_direct_bandwidth(stream_url, width, height, duration)

        if isinstance(result, dict):
            result['ffmpeg_used'] = bool(useffmpeg)
            result['ffmpeg_available'] = ffmpeg_available
            result['ffmpeg_resolution_found'] = ffmpeg_resolution_found
            result['ffmpeg_error'] = ffmpeg_error
            result['codec'] = codec
        return result
    except Exception as e:
        return {'success': False, 'error': str(e)}


def pick_hls_variant(m3u8_content, base_url):
    """从 HLS 主播放列表中选择最高分辨率/带宽的子播放列表。"""
    variants = []
    pending_stream = None

    for raw_line in m3u8_content.split('\n'):
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith('#EXT-X-STREAM-INF'):
            width, height, bandwidth = 0, 0, 0
            resolution_match = re.search(r'RESOLUTION=(\d+)x(\d+)', line)
            bandwidth_match = re.search(r'BANDWIDTH=(\d+)', line)
            if resolution_match:
                width = int(resolution_match.group(1))
                height = int(resolution_match.group(2))
            if bandwidth_match:
                bandwidth = int(bandwidth_match.group(1))
            pending_stream = {
                'width': width,
                'height': height,
                'bandwidth': bandwidth,
            }
        elif pending_stream and not line.startswith('#'):
            pending_stream['url'] = urljoin(base_url, line)
            variants.append(pending_stream)
            pending_stream = None

    if not variants:
        return None

    return max(variants, key=lambda item: (item['height'], item['width'], item['bandwidth']))


def parse_hls_segments(m3u8_content, base_url):
    """解析媒体播放列表中的分片 URL 和 EXTINF 媒体时长。"""
    segments = []
    pending_duration = None
    target_duration = 0

    for raw_line in m3u8_content.split('\n'):
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith('#EXT-X-TARGETDURATION'):
            try:
                target_duration = float(line.split(':', 1)[1])
            except (IndexError, ValueError):
                target_duration = 0
            continue

        if line.startswith('#EXTINF:'):
            try:
                pending_duration = float(line.split(':', 1)[1].split(',', 1)[0])
            except (IndexError, ValueError):
                pending_duration = None
            continue

        if not line.startswith('#'):
            segments.append({
                'url': urljoin(base_url, line),
                'duration': pending_duration or target_duration
            })
            pending_duration = None

    return segments


def test_direct_bandwidth(url, width, height, duration):
    """测试直链带宽。分辨率只认 FFmpeg 结果。"""
    try:
        deadline = time.monotonic() + max(duration, 1) + 5
        total_bytes = 0
        request_start = time.monotonic()
        connection_latency_ms = None

        with http_get(url, stream=True, timeout=request_timeout(deadline, 3, 2)) as response:
            response.raise_for_status()
            chunk_iter = response.iter_content(chunk_size=131072)

            try:
                first_chunk = next(chunk_iter)
            except StopIteration:
                first_chunk = b''
            connection_latency_ms = (time.monotonic() - request_start) * 1000
            text_probe = first_chunk.decode('utf-8', errors='ignore') if first_chunk else ''

            if is_hls_response(response, text_probe):
                hls_result = test_hls_bandwidth(response.url, width, height, duration)
                if isinstance(hls_result, dict) and hls_result.get('connection_latency_ms') is None:
                    hls_result['connection_latency_ms'] = round(connection_latency_ms, 2)
                return hls_result

            # 从第一个 chunk 到达后开始计时，排除连接建立耗时
            data_start = time.monotonic()
            last_data_time = data_start
            stall_timeout = max(duration / 2, 5)  # 无数据超时：取测试时长一半，最少 5 秒
            if first_chunk:
                total_bytes += len(first_chunk)

            for chunk in chunk_iter:
                if chunk:
                    total_bytes += len(chunk)
                    last_data_time = time.monotonic()

                # 超时标记检查：立即退出，触发 with 块关闭连接
                if _is_timed_out(url):
                    break

                # 只在数据完全停止到达时才提前退出（流断开），
                # 不因累计字节少而退出——慢启动的流可能前几秒数据少但后续正常。
                if time.monotonic() - last_data_time > stall_timeout:
                    break
                if time.monotonic() >= deadline:
                    break

        elapsed_time = time.monotonic() - data_start
        return build_bandwidth_result(width, height, total_bytes, elapsed_time, connection_latency_ms=connection_latency_ms)
    except Exception as e:
        return {'success': False, 'error': f"直链 测试失败: {str(e)}"}


def test_hls_bandwidth(url, width, height, duration):
    """测试 HLS 带宽。分辨率只认 FFmpeg 结果。"""
    try:
        deadline = time.monotonic() + max(duration, 1) + 8
        playlist_url = url
        with http_get(playlist_url, timeout=request_timeout(deadline, 3, 3)) as m3u8_resp:
            m3u8_resp.raise_for_status()
            m3u8_content = m3u8_resp.text
            playlist_url = m3u8_resp.url

        variant = pick_hls_variant(m3u8_content, playlist_url)
        if variant:
            playlist_url = variant['url']
            with http_get(playlist_url, timeout=request_timeout(deadline, 3, 3)) as m3u8_resp:
                m3u8_resp.raise_for_status()
                m3u8_content = m3u8_resp.text
                playlist_url = m3u8_resp.url

        segments = parse_hls_segments(m3u8_content, playlist_url)
        if not segments:
            return test_direct_bandwidth(url, width, height, duration)

        test_start = time.monotonic()
        total_bytes = 0
        media_seconds = 0
        download_seconds = 0
        connection_latency_ms = None
        max_retries = len(segments) * 3 if segments else 10

        for i in range(max_retries):
            now = time.monotonic()
            if now >= deadline:
                break
            if _is_timed_out(url):
                break
            if media_seconds > 3 and total_bytes < 100 * 1024:
                break
            if media_seconds >= duration:
                break

            segment = segments[i % len(segments)]
            ts_url = segment['url']
            segment_duration = segment.get('duration') or 0
            try:
                segment_request_start = time.monotonic()
                with http_get(ts_url, stream=True, timeout=request_timeout(deadline, 2, 2)) as ts_resp:
                    if ts_resp.status_code != 200:
                        continue

                    body_start = time.monotonic()
                    segment_bytes = 0
                    interrupted = False
                    try:
                        for chunk in ts_resp.iter_content(chunk_size=131072):
                            if chunk:
                                if connection_latency_ms is None:
                                    connection_latency_ms = (time.monotonic() - segment_request_start) * 1000
                                segment_bytes += len(chunk)

                            if _is_timed_out(url):
                                interrupted = True
                                break

                            now = time.monotonic()
                            if now >= deadline:
                                interrupted = True
                                break
                    finally:
                        segment_download_seconds = time.monotonic() - body_start
                        download_seconds += segment_download_seconds

                    if segment_bytes <= 0:
                        continue

                    total_bytes += segment_bytes
                    if segment_duration > 0 and not interrupted:
                        media_seconds += segment_duration
                    else:
                        media_seconds += segment_download_seconds
            except TimeoutError:
                break
            except Exception:
                if time.monotonic() - test_start >= max(duration, 1) + 8:
                    break
                continue

        if download_seconds <= 0:
            download_seconds = time.monotonic() - test_start
        if media_seconds <= 0:
            media_seconds = download_seconds

        result = build_bandwidth_result(
            width,
            height,
            total_bytes,
            download_seconds,
            basis='hls_download_elapsed',
            connection_latency_ms=connection_latency_ms
        )
        result['media_seconds'] = round(media_seconds, 2)
        result['download_seconds'] = round(download_seconds, 2)
        if download_seconds > 0:
            result['download_speed_mbps'] = round(((total_bytes / (1024 * 1024)) / download_seconds) * 8, 2)
        return result
    except Exception as e:
        return {'success': False, 'error': f"HLS 测试失败: {str(e)}"}


def load_urls_from_file(filepath='subscribe.txt'):
    """从配置文件读取地址，每行一个，忽略空行和 # 注释行。"""
    urls = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                urls.append(line)
    return urls


if __name__ == "__main__":
    try:
        urls = load_urls_from_file('subscribe.txt')
    except FileNotFoundError:
        print("未找到 subscribe.txt，请在 subscribe.txt 中每行填写一个待测地址")
        urls = []

    if not urls:
        print("subscribe.txt 中没有有效地址")
    else:
        print(f"共 {len(urls)} 个地址待测\n")
        for i, url in enumerate(urls, 1):
            print(f"[{i}/{len(urls)}] {url}")
            result = analyze_iptv_with_ffmpeg(url, duration=10, useffmpeg=True)
            if result and result.get('success'):
                print(f"  -> {result.get('resolution','?')}  "
                      f"带宽 {result.get('bandwidth_mbps', 0)} Mb/s  "
                      f"({result.get('bandwidth_basis','')})")
            else:
                reason = (result or {}).get('error', '分析失败')
                print(f"  -> 失败: {reason}")
            print()

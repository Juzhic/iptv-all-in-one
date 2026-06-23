import os
import re
import shutil
import subprocess
import threading
import time
from urllib.parse import unquote, urljoin, urlparse

import requests
import urllib3
from requests.exceptions import SSLError


# 超时 URL 注册表，供流读取循环主动退出并释放连接
_timed_out_urls = set()
_timed_out_lock = threading.Lock()


def register_timeout(url):
    """将 URL 标记为超时，正在进行的流读取会尽快退出。"""
    with _timed_out_lock:
        _timed_out_urls.add(url)


def clear_timeouts():
    """清除上一轮的超时标记，在新一轮测试开始前调用。"""
    with _timed_out_lock:
        _timed_out_urls.clear()


def _is_timed_out(url):
    """检查 URL 是否已被标记为超时。"""
    with _timed_out_lock:
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
_DEFAULT_FFMPEG_WORKERS = int(os.environ.get('MAX_FFMPEG_WORKERS', '6') or 6)
_ffmpeg_limit = max(1, _DEFAULT_FFMPEG_WORKERS)
_ffmpeg_semaphore = threading.BoundedSemaphore(_ffmpeg_limit)
_ffmpeg_lock = threading.Lock()
_ffmpeg_timeout = 5
NON_LIVE_MEDIA_EXTENSIONS = frozenset({
    '.mp4',
    '.m4v',
    '.mov',
    '.mkv',
    '.avi',
    '.wmv',
    '.webm',
    '.mpg',
    '.mpeg',
})
NON_LIVE_CONTENT_TYPE_TO_EXT = {
    'application/mp4': '.mp4',
    'video/avi': '.avi',
    'video/mp4': '.mp4',
    'video/mpeg': '.mpeg',
    'video/quicktime': '.mov',
    'video/webm': '.webm',
    'video/x-m4v': '.m4v',
    'video/x-matroska': '.mkv',
    'video/x-msvideo': '.avi',
}
STATIC_HLS_HOST_SUFFIXES = (
    'cdn.jsdelivr.net',
    'raw.githubusercontent.com',
    'github.io',
    'githubusercontent.com',
)
STATIC_HLS_PATH_KEYWORDS = (
    '/testvideo/',
    '/demo/',
    '/sample/',
    'playad',
)
STATIC_HLS_CONFIRM_MIN_DURATION = 90.0
STATIC_HLS_CONFIRM_MIN_SEGMENTS = 6
STATIC_HLS_CONFIRM_MIN_WAIT = 6.0
STATIC_HLS_CONFIRM_MAX_WAIT = 12.0


def set_ffmpeg_max_workers(limit):
    """限制同时运行的 FFmpeg 子进程数量，避免服务器瞬时进程/连接压力过高。
    注意：已在旧信号量上获取许可的线程将在旧对象上释放，不影响新信号量。
    """
    global _ffmpeg_limit, _ffmpeg_semaphore
    try:
        limit = max(1, int(limit))
    except (TypeError, ValueError):
        limit = _DEFAULT_FFMPEG_WORKERS

    with _ffmpeg_lock:
        if limit != _ffmpeg_limit:
            _ffmpeg_limit = limit
            # 使用普通 Semaphore 替代 BoundedSemaphore，避免旧持有者在旧对象上释放时抛异常
            _ffmpeg_semaphore = threading.Semaphore(_ffmpeg_limit)
    return _ffmpeg_limit


def set_ffmpeg_timeout(t):
    """设置 FFmpeg 子进程超时秒数。"""
    global _ffmpeg_timeout
    try:
        _ffmpeg_timeout = max(1, int(t))
    except (TypeError, ValueError):
        _ffmpeg_timeout = 5
    return _ffmpeg_timeout


def detect_non_live_media_url(url):
    """识别明显的点播媒体文件 URL，避免误当作直播流参与测速。"""
    try:
        parsed = urlparse((url or '').strip())
        path = unquote(parsed.path or '').lower()
    except Exception:
        return ''

    for ext in NON_LIVE_MEDIA_EXTENSIONS:
        if path.endswith(ext):
            return ext
    return ''


def detect_non_live_media_response(url, content_type=''):
    """结合最终 URL 和响应类型识别点播媒体文件。"""
    media_ext = detect_non_live_media_url(url)
    if media_ext:
        return media_ext

    normalized = (content_type or '').split(';', 1)[0].strip().lower()
    return NON_LIVE_CONTENT_TYPE_TO_EXT.get(normalized, '')


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
        import logging
        logging.getLogger(__name__).warning(f"SSL 证书验证失败，回退到 verify=False: {url[:100]}")
        return requests.get(
            url,
            timeout=timeout,
            stream=stream,
            headers=DEFAULT_HEADERS,
            allow_redirects=True,
            verify=False
        )


def read_response_text_limited(response, max_bytes=2 * 1024 * 1024):
    chunks = []
    total = 0
    encoding = response.encoding or requests.utils.get_encoding_from_headers(response.headers) or 'utf-8'
    for chunk in response.iter_content(chunk_size=65536):
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            raise ValueError(f"响应内容超过 {max_bytes // 1024 // 1024}MB")
        chunks.append(chunk)
    return b''.join(chunks).decode(encoding, errors='ignore')


def fetch_hls_playlist(url, deadline):
    """获取 HLS 播放列表文本，并返回最终 URL。"""
    with http_get(url, timeout=request_timeout(deadline, 3, 3), stream=True) as response:
        response.raise_for_status()
        return response.url, read_response_text_limited(response)


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
        with http_get(url, timeout=request_timeout(deadline, 3, 3), stream=True) as response:
            response.raise_for_status()
            probe_bytes = b''
            for chunk in response.iter_content(chunk_size=4096):
                if chunk:
                    probe_bytes = chunk[:4096]
                    break
            text_probe = probe_bytes.decode('utf-8', errors='ignore')
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
        '-allowed_segment_extensions', 'ALL',
        '-extension_picky', '0',
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
        with _ffmpeg_semaphore:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            try:
                _, stderr_bytes = proc.communicate(timeout=_ffmpeg_timeout)
                stderr_output = stderr_bytes.decode('utf-8', errors='ignore') if stderr_bytes else ''
            except subprocess.TimeoutExpired:
                proc.kill()
                _, stderr_bytes = proc.communicate()
                stderr_output = stderr_bytes.decode('utf-8', errors='ignore') if stderr_bytes else ''
    except Exception as e:
        return {'success': False, 'width': 0, 'height': 0, 'error': f"FFmpeg 启动失败: {e}"}

    if isinstance(stderr_output, bytes):
        stderr_output = stderr_output.decode('utf-8', errors='ignore')

    resolution_match = re.search(r'(?:Stream.*?Video:|Video:).*?(\d{3,5})x(\d{3,5})', stderr_output)
    if not resolution_match:
        # Fallback: match any resolution pattern in stderr
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
        non_live_ext = detect_non_live_media_url(url)
        if non_live_ext:
            return {'success': False, 'error': f'疑似点播文件({non_live_ext})，已排除'}
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


def parse_hls_playlist_metadata(m3u8_content, base_url):
    """提取 HLS 媒体播放列表特征，用于区分直播与静态测试源。"""
    playlist_type = ''
    target_duration = 0.0
    media_sequence = None
    has_endlist = False

    for raw_line in m3u8_content.split('\n'):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith('#EXT-X-PLAYLIST-TYPE:'):
            playlist_type = line.split(':', 1)[1].strip().lower()
        elif line.startswith('#EXT-X-TARGETDURATION:'):
            try:
                target_duration = float(line.split(':', 1)[1])
            except (IndexError, ValueError):
                target_duration = 0.0
        elif line.startswith('#EXT-X-MEDIA-SEQUENCE:'):
            try:
                media_sequence = int(line.split(':', 1)[1])
            except (IndexError, ValueError):
                media_sequence = None
        elif line == '#EXT-X-ENDLIST':
            has_endlist = True

    segments = parse_hls_segments(m3u8_content, base_url)
    total_duration = 0.0
    segment_urls = []
    for segment in segments:
        segment_urls.append(segment.get('url', ''))
        try:
            total_duration += float(segment.get('duration') or 0)
        except (TypeError, ValueError):
            pass

    return {
        'playlist_type': playlist_type,
        'target_duration': target_duration,
        'media_sequence': media_sequence,
        'has_endlist': has_endlist,
        'segment_count': len(segments),
        'total_duration': round(total_duration, 3),
        'segment_urls': segment_urls,
        'segments': segments,
    }


def get_static_hls_hints(playlist_url, metadata):
    """返回静态 HLS 测试源的可疑特征。"""
    flags = []
    try:
        parsed = urlparse(playlist_url or '')
        host = (parsed.netloc or '').lower()
        path = unquote(parsed.path or '').lower()
    except Exception:
        host = ''
        path = ''

    if any(host == suffix or host.endswith('.' + suffix) for suffix in STATIC_HLS_HOST_SUFFIXES):
        flags.append('static_host')
    if any(keyword in path for keyword in STATIC_HLS_PATH_KEYWORDS):
        flags.append('static_path')
    if metadata.get('media_sequence') == 0:
        flags.append('sequence_zero')
    if metadata.get('total_duration', 0) >= STATIC_HLS_CONFIRM_MIN_DURATION:
        flags.append('fixed_duration')
    return flags


def build_hls_playlist_fingerprint(metadata):
    """构建用于二次确认的播放列表指纹。"""
    return (
        metadata.get('playlist_type', ''),
        bool(metadata.get('has_endlist')),
        metadata.get('media_sequence'),
        int(metadata.get('segment_count', 0) or 0),
        round(float(metadata.get('total_duration', 0) or 0), 3),
        tuple(metadata.get('segment_urls', [])[-5:]),
    )


def detect_non_live_hls_playlist(playlist_url, m3u8_content, deadline):
    """识别静态 HLS、点播清单或测试片源。"""
    metadata = parse_hls_playlist_metadata(m3u8_content, playlist_url)
    playlist_type = metadata.get('playlist_type', '')
    if playlist_type == 'vod':
        return True, 'playlist-type=VOD', metadata
    if metadata.get('has_endlist'):
        return True, 'playlist contains ENDLIST', metadata

    hints = get_static_hls_hints(playlist_url, metadata)
    should_confirm = (
        metadata.get('segment_count', 0) >= STATIC_HLS_CONFIRM_MIN_SEGMENTS
        and metadata.get('media_sequence') == 0
        and any(flag in hints for flag in ('fixed_duration', 'static_host', 'static_path'))
    )
    if not should_confirm:
        return False, '', metadata

    wait_seconds = metadata.get('target_duration') or 0
    wait_seconds = max(wait_seconds, STATIC_HLS_CONFIRM_MIN_WAIT)
    wait_seconds = min(wait_seconds, STATIC_HLS_CONFIRM_MAX_WAIT)
    if deadline - time.monotonic() <= wait_seconds + 1:
        return False, '', metadata

    time.sleep(wait_seconds)
    refreshed_url, refreshed_content = fetch_hls_playlist(playlist_url, deadline)
    refreshed_metadata = parse_hls_playlist_metadata(refreshed_content, refreshed_url)
    if build_hls_playlist_fingerprint(metadata) == build_hls_playlist_fingerprint(refreshed_metadata):
        return True, 'static HLS playlist confirmed by re-fetch', refreshed_metadata
    return False, '', refreshed_metadata


def test_direct_bandwidth(url, width, height, duration):
    """测试直链带宽。分辨率只认 FFmpeg 结果。"""
    try:
        deadline = time.monotonic() + max(duration, 1) + 5
        total_bytes = 0
        request_start = time.monotonic()
        connection_latency_ms = None

        with http_get(url, stream=True, timeout=request_timeout(deadline, 3, 2)) as response:
            response.raise_for_status()
            non_live_ext = detect_non_live_media_response(
                response.url or url,
                response.headers.get('content-type', '')
            )
            if non_live_ext:
                return {'success': False, 'error': f'疑似点播文件({non_live_ext})，已排除'}
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
        playlist_url, m3u8_content = fetch_hls_playlist(url, deadline)

        variant = pick_hls_variant(m3u8_content, playlist_url)
        if variant:
            playlist_url, m3u8_content = fetch_hls_playlist(variant['url'], deadline)

        is_non_live_hls, non_live_reason, metadata = detect_non_live_hls_playlist(
            playlist_url,
            m3u8_content,
            deadline
        )
        if is_non_live_hls:
            return {'success': False, 'error': f'疑似非直播HLS({non_live_reason})，已排除'}

        segments = metadata.get('segments') or parse_hls_segments(m3u8_content, playlist_url)
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

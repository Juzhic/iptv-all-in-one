import requests
import time
import subprocess
import re
import sys
import os
import signal
from urllib.parse import urljoin


def ffmpeg_test(url):
    """
    独立出来的 FFmpeg 测试方法
    用于获取视频分辨率
    """
    # --- 核心配置：去掉 -stimeout 防止误杀慢启动源 ---
    cmd = [
        'ffmpeg',
        '-probesize', '512000',  # 减小探测包大小
        '-analyzeduration', '2000000',  # 限制分析时长 2秒
        '-fflags', '+nobuffer',  # 禁用缓冲，即时输出
        '-flags', 'low_delay',  # 强制低延迟解码
        '-i', url,
        '-t', '3',  # 只要分析前3秒
        '-f', 'null',
        '-'
    ]

    if sys.platform.startswith('win'):
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
        preexec_fn = None
    else:
        creationflags = 0
        preexec_fn = os.setsid

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='ignore',
            creationflags=creationflags,
            preexec_fn=preexec_fn
        )
    except Exception as e:
        print(f"❌ FFmpeg 启动失败: {e}")
        return 0, 0

    stderr_output = ''
    ffmpeg_start = time.time()
    max_ffmpeg_wait = 3

    while True:
        if process.poll() is not None:
            remaining = process.stderr.read()
            if remaining: stderr_output += remaining
            break

        output = process.stderr.read(4096)
        if output: stderr_output += output

        # Python 层面的硬超时
        if time.time() - ffmpeg_start > max_ffmpeg_wait:
            try:
                if sys.platform.startswith('win'):
                    os.kill(process.pid, signal.CTRL_BREAK_EVENT)
                else:
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except:
                pass
            break
        time.sleep(0.05)

    # 解析分辨率
    resolution_pattern = r'(\d{3,5})x(\d{3,5})'
    resolution_match = re.search(resolution_pattern, stderr_output)
    width, height = 0, 0
    if resolution_match:
        width = int(resolution_match.group(1))
        height = int(resolution_match.group(2))

    return width, height


def analyze_iptv_with_ffmpeg(url, duration=10, useffmpeg=False):
    """
    智能分析入口
    useffmpeg: 是否强制使用 FFmpeg 获取分辨率。
               False (默认): 不跑 FFmpeg，直接测速。如果网速快则默认 1080P。
               True: 先跑 FFmpeg 获取分辨率，再测速。
    """
    try:
        width, height = 0, 0

        # ==========================================
        # 1. 条件性执行 FFmpeg
        # ==========================================
        if useffmpeg:
            width, height = ffmpeg_test(url)
            # print(f"FFmpeg 解析结果: {width}x{height}")

        # ==========================================
        # 2. 智能带宽测试 (包含分辨率兜底逻辑)
        # ==========================================
        if '.m3u8' in url:
            return test_hls_bandwidth(url, width, height, duration)
        else:
            return test_direct_bandwidth(url, width, height, duration)

    except Exception as e:
        return {'success': False, 'error': str(e)}


def test_direct_bandwidth(url, width, height, duration):
    """测试直链带宽 + 分辨率兜底"""
    try:
        start_time = time.time()
        total_bytes = 0

        response = requests.get(url, stream=True, timeout=(3, 5))
        response.raise_for_status()

        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                total_bytes += len(chunk)

            current_elapsed = time.time() - start_time
            # 快速失败机制
            if current_elapsed > 3 and total_bytes < 100 * 1024:
                break
            if current_elapsed >= duration:
                break

        elapsed_time = time.time() - start_time
        if elapsed_time == 0: elapsed_time = 1

        speed_mbps = (total_bytes / (1024 * 1024)) / elapsed_time
        bitrate_mbps = speed_mbps * 8

        # ==========================================
        # 【核心修改】分辨率兜底逻辑
        # ==========================================
        final_width, final_height = width, height

        # 如果分辨率为 0 (未使用 FFmpeg 或 FFmpeg 失败) 且 网速 > 1.5MB/s
        # 强制认为是 1080P
        if width == 0 and speed_mbps > 1.5:
            final_width, final_height = 1920, 1080

        return {'width': final_width, 'height': final_height, 'resolution': f"{final_width}x{final_height}",
                'bitrate_mbps': round(bitrate_mbps, 2), 'speed_mbps': round(speed_mbps, 2), 'success': True}

    except Exception as e:
        return {'success': False, 'error': f"直链 测试失败: {str(e)}"}


def test_hls_bandwidth(url, width, height, duration):
    """测试 HLS 带宽 + 分辨率兜底"""
    try:
        m3u8_resp = requests.get(url, timeout=(3, 5))
        m3u8_resp.raise_for_status()
        m3u8_content = m3u8_resp.text

        ts_urls = []
        lines = m3u8_content.split('\n')

        for line in lines:
            line = line.strip()
            if '.ts' in line and not line.startswith('#'):
                full_url = urljoin(url, line)
                ts_urls.append(full_url)

        ts_urls = list(dict.fromkeys(ts_urls))

        if not ts_urls:
            return test_direct_bandwidth(url, width, height, duration)

        start_time = time.time()
        total_bytes = 0
        downloaded_count = 0
        max_retries = len(ts_urls) * 3 if len(ts_urls) > 0 else 10

        for i in range(max_retries):
            current_elapsed = time.time() - start_time
            if current_elapsed > 3 and total_bytes < 100 * 1024:
                break
            if current_elapsed >= duration:
                break

            ts_url = ts_urls[i % len(ts_urls)]

            try:
                ts_resp = requests.get(ts_url, timeout=(2, 4))
                if ts_resp.status_code == 200:
                    total_bytes += len(ts_resp.content)
                    downloaded_count += 1
            except:
                continue

        elapsed_time = time.time() - start_time
        if elapsed_time == 0: elapsed_time = 1

        speed_mbps = (total_bytes / (1024 * 1024)) / elapsed_time
        bitrate_mbps = speed_mbps * 8

        # ==========================================
        # 【核心修改】分辨率兜底逻辑
        # ==========================================
        final_width, final_height = width, height

        # 如果分辨率为 0 且 网速 > 1.5MB/s，强制认为是 1080P
        if width == 0 and speed_mbps >= 1:
            final_width, final_height = 1920, 1080

        return {'width': final_width, 'height': final_height, 'resolution': f"{final_width}x{final_height}",
                'bitrate_mbps': round(bitrate_mbps, 2), 'speed_mbps': round(speed_mbps, 2), 'success': True}

    except Exception as e:
        return {'success': False, 'error': f"HLS 测试失败: {str(e)}"}


if __name__ == "__main__":
    # 测试链接
    iptv_url = "http://101.66.194.65:9901/tsfile/live/0123_1.m3u8?key=txiptv&playlive=0&authid=0"

    print("--- 测试 1: 不使用 FFmpeg (默认, 快速模式) ---")
    result1 = analyze_iptv_with_ffmpeg(iptv_url, duration=10, useffmpeg=False)
    if result1:
        print(f"结果: {result1}")

    print("\n--- 测试 2: 使用 FFmpeg (精确模式) ---")
    result2 = analyze_iptv_with_ffmpeg(iptv_url, duration=10, useffmpeg=True)
    if result2:
        print(f"结果: {result2}")
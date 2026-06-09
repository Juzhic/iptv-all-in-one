# video_check.py
import asyncio
import time
import re
import os
import struct
import statistics
from urllib.parse import urlparse
import aiohttp
from datetime import datetime
from . import config_bridge
from .config_bridge import (
    HEAD_TIMEOUT, STREAM_CHECK_TIMEOUT, DEEP_CHECK_DURATION,
    CONCURRENT_FAST, CONCURRENT_DEEP, MIN_BANDWIDTH, MIN_WIDTH, MIN_HEIGHT,
    MAX_DELAY_MS, AUTO_REFILL_QUAKE_SIZE, FAIL_THRESHOLD,
    STABILITY_THRESHOLD_NATIONAL, STABILITY_THRESHOLD_LOCAL
)
from .channel_utils import resolve_name, channel_sort_key, append_unmatched_to_alias
from .network import global_sem, get_session
# 模块级状态变量（由 background_deep_update / health_check 管理）
LATEST_CHANNELS = []
QUICK_CHANNELS = []
LAST_UPDATE_TIME = None
failure_count = {}
update_progress = {"percent": 0, "message": "空闲"}
from .logger_bridge import logger

# ========== 性能优化：限制 ffprobe 子进程并发数 ==========
FFPROBE_SEM = asyncio.Semaphore(3)   # 最多同时运行 3 个 ffprobe，避免 CPU 飙升
# =====================================================

# ==================== 轻量级 H.264 分辨率解析 ====================
def parse_h264_resolution(data: bytes):
    if len(data) >= 188 and data[0] == 0x47:
        pid_payloads = {}
        for i in range(0, len(data) - 187, 188):
            ts_pkt = data[i:i+188]
            if ts_pkt[0] != 0x47:
                break
            pid = ((ts_pkt[1] & 0x1F) << 8) | ts_pkt[2]
            if pid not in pid_payloads:
                pid_payloads[pid] = b''
            pid_payloads[pid] += ts_pkt[4:]
        video_pid = None
        for pid in sorted(pid_payloads.keys()):
            if 0x100 <= pid <= 0x1FF:
                video_pid = pid
                break
        if video_pid:
            data = pid_payloads[video_pid]

    sps_start = data.find(b'\x00\x00\x00\x01\x67')
    if sps_start == -1:
        sps_start = data.find(b'\x00\x00\x01\x67')
    if sps_start == -1:
        return None, None

    sps = data[sps_start:]
    offset = 5
    if len(sps) < offset + 4:
        return None, None

    profile_idc = sps[offset - 1]
    if profile_idc not in (66, 77, 88, 100, 110, 122, 244):
        return None, None

    def exp_golomb(data, pos):
        bit_count = 0
        while pos // 8 < len(data) and not (data[pos // 8] & (0x80 >> (pos % 8))):
            bit_count += 1
            pos += 1
        pos += 1
        result = 0
        for _ in range(bit_count):
            bit = (data[pos // 8] >> (7 - pos % 8)) & 1 if pos // 8 < len(data) else 0
            result = (result << 1) | bit
            pos += 1
        return (1 << bit_count) - 1 + result, pos

    try:
        pos = offset * 8
        _, pos = exp_golomb(sps, pos)
        _, pos = exp_golomb(sps, pos)
        poc_type, pos = exp_golomb(sps, pos)
        if poc_type == 0:
            _, pos = exp_golomb(sps, pos)
        elif poc_type == 1:
            pos += 1
            _, pos = exp_golomb(sps, pos)
            _, pos = exp_golomb(sps, pos)
            num_ref_frames, pos = exp_golomb(sps, pos)
            for _ in range(num_ref_frames):
                _, pos = exp_golomb(sps, pos)
        _, pos = exp_golomb(sps, pos)
        pos += 1
        pic_width_in_mbs, pos = exp_golomb(sps, pos)
        pic_height_in_mbs, pos = exp_golomb(sps, pos)
        frame_mbs_only_flag = (sps[pos // 8] >> (7 - pos % 8)) & 1
        pos += 1

        width = (pic_width_in_mbs + 1) * 16
        height = (pic_height_in_mbs + 1) * 16 * (2 - frame_mbs_only_flag)
        return width, height
    except:
        return None, None

async def get_video_info_light(url):
    try:
        async with aiohttp.ClientSession() as session:
            headers = {'Range': 'bytes=0-65535'}
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=3)) as resp:
                data = await resp.content.read(65536)
        w, h = parse_h264_resolution(data)
        if w and h:
            return (f"{w}×{h}", "h264")
    except:
        pass
    return await get_video_info(url)

async def get_video_info(url):
    """获取视频分辨率，使用信号量限制 ffprobe 并发"""
    async with FFPROBE_SEM:
        try:
            cmd = [
                'ffprobe', '-v', 'error',
                '-select_streams', 'v:0',
                '-show_entries', 'stream=width,height,codec_name',
                '-of', 'csv=p=0',
                '-probesize', '256k',
                '-analyzeduration', '1000000',
                '-timeout', str(STREAM_CHECK_TIMEOUT * 1000000),
                url
            ]
            proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=STREAM_CHECK_TIMEOUT + 2)
            except asyncio.TimeoutError:
                proc.kill()
                return ("未知", "unknown")
            if proc.returncode == 0 and stdout:
                parts = stdout.decode().strip().split(',')
                if len(parts) >= 3:
                    return (f"{parts[0]}×{parts[1]}", parts[2])
                elif len(parts) == 2:
                    return (f"{parts[0]}×{parts[1]}", "unknown")
            return ("未知", "unknown")
        except Exception as e:
            logger.debug(f"ffprobe 失败 {url}: {e}")
            return ("未知", "unknown")

def filter_hd(channels, min_width=MIN_WIDTH, min_height=MIN_HEIGHT, drop_unknown=False):
    hd, dropped = [], 0
    for c in channels:
        res = c.get('resolution', '')
        if not res or res == '未知':
            if drop_unknown:
                dropped += 1
                continue
            hd.append(c)
        else:
            try:
                w, h = map(int, res.replace('×', 'x').split('x'))
                if w >= min_width and h >= min_height:
                    hd.append(c)
                else:
                    dropped += 1
            except:
                if drop_unknown:
                    dropped += 1
                else:
                    hd.append(c)
    if dropped:
        logger.info(f"[分辨率] 丢弃 {dropped} 个")
    return hd

def filter_high_delay(channels, max_delay=MAX_DELAY_MS):
    before = len(channels)
    filtered = [c for c in channels if not (isinstance(c.get('delay'), (int, float)) and c['delay'] > max_delay)]
    removed = before - len(filtered)
    if removed:
        logger.info(f"[延迟] 丢弃 {removed} 个")
    return filtered

async def fast_check_with_fallback(session, url):
    async with global_sem:
        try:
            async with session.head(url, timeout=aiohttp.ClientTimeout(total=HEAD_TIMEOUT), allow_redirects=True) as r:
                if r.status == 200:
                    return True
        except:
            pass
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=HEAD_TIMEOUT + 2), allow_redirects=True) as r:
                if r.status != 200:
                    return False
                total = 0
                async for chunk in r.content.iter_chunked(2048):
                    total += len(chunk)
                    if total >= 4096:
                        return True
                return total > 0
        except:
            return False

async def fast_filter(sources):
    start = time.time()
    sem = asyncio.Semaphore(CONCURRENT_FAST)
    total = len(sources)
    done = [0]
    logger.info(f"[快速检测] {total} 源，并发={CONCURRENT_FAST}")
    async with get_session(limit=CONCURRENT_FAST, timeout=HEAD_TIMEOUT + 3) as session:
        async def run(src):
            if urlparse(src['url']).scheme not in ('http', 'https'):
                done[0] += 1
                return None
            async with sem:
                ok = await fast_check_with_fallback(session, src['url'])
                done[0] += 1
                if done[0] % 200 == 0 or done[0] == total:
                    elapsed = time.time() - start
                    speed = done[0] / elapsed if elapsed > 0 else 0
                    logger.info(f"[快速检测] {done[0]}/{total}  {speed:.1f}/s")
                if ok:
                    entry = {**src, 'protocol': 'http', 'delay': '', 'bandwidth': '', 'resolution': '', 'codec': '', 'stability': 0}
                    if entry.get('ip_province') and not entry.get('name_province'):
                        entry['stability'] = 60
                    if 'category' not in entry:
                        entry['category'] = resolve_name(entry['name'])[1]
                    return entry
                return None
        tasks = [run(s) for s in sources]
        results = await asyncio.gather(*tasks)
    valid = [r for r in results if r]
    elapsed = time.time() - start
    logger.info(f"[快速检测] 成功 {len(valid)}/{total}，耗时 {elapsed:.1f}s")
    return valid

async def deep_check(session, url, check_duration=6):   # 测速时长增至 6 秒
    async with global_sem:
        try:
            start = time.time()
            total_bytes = 0
            chunk_count = 0
            empty_count = 0
            max_interval = 0
            last_chunk = start
            intervals = []                     # 记录所有 chunk 间隔，用于计算抖动
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10), allow_redirects=True) as r:
                if r.status != 200:
                    return None
                if 'text/html' in r.headers.get('Content-Type', ''):
                    return None
                async for chunk in r.content.iter_chunked(4096):
                    now = time.time()
                    size = len(chunk)
                    total_bytes += size
                    chunk_count += 1
                    if size == 0:
                        empty_count += 1
                    else:
                        interval = now - last_chunk
                        intervals.append(interval)
                        if interval > max_interval:
                            max_interval = interval
                        last_chunk = now
                    if now - start > check_duration or total_bytes >= 131072:   # 至少 128KB 数据
                        break
                elapsed = time.time() - start
                if total_bytes == 0:
                    return None
                delay = round(elapsed * 1000, 1)
                bandwidth = round(total_bytes / elapsed / 1024, 2) if elapsed > 0 else 0

                # 计算抖动：相邻 chunk 间隔的标准差 (单位秒)
                jitter = statistics.stdev(intervals) if len(intervals) > 1 else 0.0
                # 稳定性评分基础 100
                stability = 100.0

                # 1. 空包惩罚
                if chunk_count > 0:
                    empty_rate = empty_count / chunk_count
                    if empty_rate > 0.1:
                        stability -= 35
                    elif empty_rate > 0.05:
                        stability -= 20

                # 2. 最大间隔惩罚（卡顿时长）
                if max_interval > 1.5:
                    stability -= 30
                elif max_interval > 0.8:
                    stability -= 15
                elif max_interval > 0.5:
                    stability -= 8

                # 3. 抖动惩罚：间隔波动大影响播放平滑度
                if jitter > 0.5:
                    stability -= 25
                elif jitter > 0.2:
                    stability -= 12
                elif jitter > 0.1:
                    stability -= 5

                # 4. 带宽惩罚（至少 200KB/s 流畅）
                if bandwidth < 200:
                    stability -= 40
                elif bandwidth < 300:
                    stability -= 20
                elif bandwidth < 500:
                    stability -= 10

                # 5. 延迟惩罚
                if delay > 2000:
                    stability -= 20
                elif delay > 1000:
                    stability -= 10

                # 限制在 0-100 之间
                stability = max(0, min(100, stability))

                return {
                    'delay': delay,
                    'bandwidth': bandwidth,
                    'stability': int(stability),
                    'chunk_count': chunk_count,
                    'jitter': jitter
                }
        except Exception as e:
            logger.debug(f"deep_check 异常 {url}: {e}")
            return None

async def deep_filter_batch(batch, sem, session):
    async def work(src):
        async with sem:
            perf = await deep_check(session, src['url'])
            if not perf:
                return None
            src['delay'] = perf['delay']
            src['bandwidth'] = perf['bandwidth']
            src['stability'] = perf['stability']
            res, codec = await get_video_info_light(src['url'])
            src['resolution'] = res
            src['codec'] = codec
            return src
    results = await asyncio.gather(*[work(s) for s in batch])
    return [r for r in results if r is not None]

async def background_deep_update(initial_list):
    global LATEST_CHANNELS, QUICK_CHANNELS, LAST_UPDATE_TIME, failure_count, update_progress
    working = initial_list.copy()
    total = len(working)
    if total == 0:
        return
    BATCH = 30
    sem = asyncio.Semaphore(CONCURRENT_DEEP)
    logger.info(f"🔍 深度测速（并发={CONCURRENT_DEEP}），总数 {total}")
    start_time = time.time()
    stats = {'stable': 0, 'low_bw': 0, 'dead': 0}
    async with get_session(limit=CONCURRENT_DEEP, timeout=12, force_close=True) as session:
        new_list = []
        for i in range(0, total, BATCH):
            batch = working[i:i+BATCH]
            updated = await deep_filter_batch(batch, sem, session)
            stable_upd = []
            for ch in updated:
                s = ch.get('stability', 0)
                bw = ch.get('bandwidth', 0)
                if s >= 30:
                    stable_upd.append(ch)
                    stats['stable'] += 1
                elif bw < MIN_BANDWIDTH:
                    stats['low_bw'] += 1
                else:
                    stats['dead'] += 1
            new_list.extend(stable_upd)
            new_list = filter_hd(filter_high_delay(new_list))
            # 按稳定性、带宽、延迟综合排序（供实时展示用）
            new_list.sort(key=lambda c: (-c.get('stability', 0), -c.get('bandwidth', 0), c.get('delay', 9999)))
            LATEST_CHANNELS = new_list
            QUICK_CHANNELS = new_list
            LAST_UPDATE_TIME = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            for ch in new_list:
                failure_count[ch['url']] = 0
            progress = min(int((i + len(batch)) / total * 100), 100)
            update_progress["percent"] = progress
            update_progress["message"] = f"深度测速 {progress}% (稳定:{stats['stable']})"
            bar = '█' * (progress // 3) + '░' * (30 - progress // 3)
            print(f"\r🔄 [{bar}] {progress}% 有效:{len(new_list)} 稳定:{stats['stable']}", end='', flush=True)
            await asyncio.sleep(0)
    print()
    elapsed = time.time() - start_time
    logger.info(f"✅ 深度测速完成，稳定:{stats['stable']} 总有效:{len(QUICK_CHANNELS)} 耗时:{elapsed:.1f}s")
    unknown = [
        c for c in QUICK_CHANNELS
        if c.get('province') == '未知' and c.get('category') not in (
            '央视频道', '卫视频道', '央视付费频道', '电影频道', '港澳台频道'
        )
    ]
    if unknown:
        unames = sorted(list({c['name'] for c in unknown}))
        logger.info(f"⚠️ {len(unknown)}个频道省份未知（去重{len(unames)}），建议补充alias.txt:")
        for n in unames:
            logger.info(f"    {n}")
        append_unmatched_to_alias(unames)

async def quick_stream_check(session, url):
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=4), allow_redirects=True) as r:
            if r.status != 200:
                return False
            total = 0
            async for chunk in r.content.iter_chunked(2048):
                total += len(chunk)
                if total >= 4096:
                    return True
            return total > 0
    except:
        return False

async def health_check():
    global QUICK_CHANNELS, LATEST_CHANNELS, failure_count, LAST_UPDATE_TIME
    channels = QUICK_CHANNELS.copy() or []
    if not channels:
        return
    sem = asyncio.Semaphore(30)
    async with get_session(limit=30, timeout=6) as session:
        async def check_one(ch):
            if urlparse(ch['url']).scheme not in ('http', 'https'):
                return ch, True
            async with sem:
                ok = await quick_stream_check(session, ch['url'])
                if not ok:
                    failure_count[ch['url']] = failure_count.get(ch['url'], 0) + 1
                    if failure_count[ch['url']] >= FAIL_THRESHOLD:
                        return ch, False
                else:
                    failure_count[ch['url']] = 0
                return ch, True
        results = await asyncio.gather(*[check_one(c) for c in channels])
    kept = [r[0] for r in results if r[1]]
    removed = len(channels) - len(kept)
    if removed > 0:
        kept.sort(key=lambda c: (-c.get('stability', 0), -c.get('bandwidth', 0), c.get('delay', 9999)))
        QUICK_CHANNELS = LATEST_CHANNELS = kept
        LAST_UPDATE_TIME = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        logger.info(f"[健康检查] 移除 {removed} 个，保留 {len(kept)}")

async def trigger_refill():
    global QUICK_CHANNELS, LATEST_CHANNELS
    from .platforms import collect_all
    new_entries = await collect_all(size=AUTO_REFILL_QUAKE_SIZE)
    if not new_entries:
        return
    existing = {c['url'] for c in QUICK_CHANNELS}
    unique_new = [e for e in new_entries if e['url'] not in existing]
    if not unique_new:
        return
    verified = await fast_filter(unique_new)
    if verified:
        combined = QUICK_CHANNELS + verified
        combined.sort(key=lambda c: (-c.get('stability', 0), -c.get('bandwidth', 0), c.get('delay', 9999)))
        QUICK_CHANNELS = LATEST_CHANNELS = combined
        asyncio.create_task(background_deep_update(combined))
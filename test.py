"""
IPTV 质量筛选 - 快速测试版本（仅测试前 10 个频道）
用于验证功能和测试性能
"""
import time
import requests
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from FFmpegTest import analyze_iptv_with_ffmpeg


def fetch_m3u_playlist(url):
    """从指定 URL 获取 M3U 播放列表数据"""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.text
    except Exception as e:
        print(f"获取 M3U 数据失败：{e}")
        return None


def parse_iptv_addresses(m3u_content):
    """解析 M3U 内容，提取 IPTV 组播地址"""
    iptv_list = []
    lines = m3u_content.split('\n')
    current_channel = {}
    
    for line in lines:
        line = line.strip()
        if not line or (line.startswith('#') and not line.startswith('#EXTINF')):
            continue
        
        if line.startswith('#EXTINF'):
            match = re.search(r'group-title="([^"]*)".*?,(.+)$', line)
            if match:
                current_channel['group'] = match.group(1)
                current_channel['name'] = match.group(2).strip()
            else:
                parts = line.split(',')
                if len(parts) > 1:
                    current_channel['name'] = parts[-1].strip()
        
        elif line.startswith('http://') or line.startswith('https://'):
            if '/rtp/' in line or '239.' in line or '.m3u8' in line or 'live/' in line:
                iptv_list.append((current_channel.copy(), line))
                current_channel = {}
    
    return iptv_list


def test_iptv_quality(url, duration=30):
    """测试 IPTV 流的质量"""
    result = analyze_iptv_with_ffmpeg(url, duration)
    
    if not result or not result.get('success'):
        return {'pass': False, 'reason': '分析失败'}
    
    width = result.get('width', 0)
    height = result.get('height', 0)
    speed_mbps = result.get('speed_mbps', 0)
    
    resolution_pass = (width >= 1920 and height >= 1080)
    bandwidth_pass = speed_mbps > 1.0
    passed = resolution_pass and bandwidth_pass
    
    return {
        'pass': passed,
        'resolution': f"{width}x{height}",
        'speed_mbps': speed_mbps,
        'bitrate_mbps': result.get('bitrate_mbps', 0),
        'resolution_pass': resolution_pass,
        'bandwidth_pass': bandwidth_pass
    }


def filter_and_save_playlist(iptv_list, output_file='test_list.m3u', duration=30, max_workers=5):
    """过滤并保存符合条件的 IPTV 列表"""
    filtered_list = []
    total = len(iptv_list)
    
    print(f"\n开始测试 {total} 个 IPTV 地址...")
    print(f"并发线程数：{max_workers}")
    print(f"预计总时间：约 {(total * duration) / (max_workers * 60):.1f} 分钟\n")
    
    processed = 0
    failed = 0
    
    def test_single_channel(args):
        idx, (channel_info, url) = args
        name = channel_info.get('name', '未知')
        
        try:
            result = analyze_iptv_with_ffmpeg(url, duration)
            
            if not result or not result.get('success'):
                return {
                    'index': idx,
                    'channel_info': channel_info,
                    'url': url,
                    'pass': False,
                    'reason': '分析失败'
                }
            
            width = result.get('width', 0)
            height = result.get('height', 0)
            speed_mbps = result.get('speed_mbps', 0)
            
            resolution_pass = (width >= 1920 and height >= 1080)
            bandwidth_pass = speed_mbps > 1.0
            passed = resolution_pass and bandwidth_pass
            
            return {
                'index': idx,
                'channel_info': channel_info,
                'url': url,
                'test_result': {
                    'pass': passed,
                    'resolution': f"{width}x{height}",
                    'speed_mbps': speed_mbps,
                    'bitrate_mbps': result.get('bitrate_mbps', 0),
                    'resolution_pass': resolution_pass,
                    'bandwidth_pass': bandwidth_pass
                }
            }
        except Exception as e:
            return {
                'index': idx,
                'channel_info': channel_info,
                'url': url,
                'pass': False,
                'reason': str(e)
            }
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(test_single_channel, item): i 
                  for i, item in enumerate(enumerate(iptv_list, 1))}
        
        for future in as_completed(futures):
            result = future.result()
            processed += 1
            
            idx = result['index']
            channel_info = result['channel_info']
            url = result['url']
            name = channel_info.get('name', '未知')
            
            print(f"\n[{processed}/{total}] [{idx}] {name}")
            print(f"   URL: {url}")
            
            if result.get('pass') and result.get('test_result'):
                test_result = result['test_result']
                if test_result['pass']:
                    print(f"   ✓ 符合条件！分辨率：{test_result['resolution']}, "
                          f"带宽：{test_result['speed_mbps']:.2f} MB/s")
                    filtered_list.append((channel_info, url))
                else:
                    reason = []
                    if not test_result.get('resolution_pass'):
                        reason.append(f"分辨率不足 ({test_result['resolution']})")
                    if not test_result.get('bandwidth_pass'):
                        reason.append(f"带宽不足 ({test_result['speed_mbps']:.2f} MB/s)")
                    print(f"   ✗ 不符合条件：{', '.join(reason)}")
                    failed += 1
            else:
                print(f"   ✗ 测试失败：{result.get('reason', '未知错误')}")
                failed += 1
            
            progress = (processed / total) * 100
            print(f"   进度：{progress:.1f}% (成功：{len(filtered_list)}, 失败：{failed})")
    
    save_to_m3u(filtered_list, output_file)
    
    print(f"\n" + "="*60)
    print(f"测试完成！")
    if total > 0:
        print(f"共测试：{total} 个地址")
        print(f"符合条件：{len(filtered_list)} 个")
        print(f"不符合/失败：{failed} 个")
        print(f"成功率：{(len(filtered_list)/total)*100:.1f}%")
    else:
        print("警告：没有可测试的地址")
    print(f"已保存到：{output_file}")
    print("="*60)


def save_to_m3u(iptv_list, output_file):
    """将 IPTV 列表保存为 M3U 格式"""
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('#EXTM3U x-tvg-url="https://live.fanmingming.cn/e.xml"\n')
        
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
    m3u_url = "http://120.26.145.99:50085/sub?wxfmk4X8=m3u"
    
    # 配置参数（快速测试）
    TEST_DURATION = 30      # 每个频道测试时长（秒）
    MAX_WORKERS = 5         # 最大并发线程数
    OUTPUT_FILE = 'test_list.m3u'  # 输出文件名
    MAX_CHANNELS = 10       # 只测试前 10 个频道
    
    print("="*60)
    print("IPTV 频道质量筛选工具 - 快速测试版")
    print("="*60)
    print(f"数据源：{m3u_url}")
    print(f"测试频道数：最多 {MAX_CHANNELS} 个")
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
        
        # 只取前 10 个频道
        if len(iptv_list) > MAX_CHANNELS:
            iptv_list = iptv_list[:MAX_CHANNELS]
            print(f"限定测试数量：{MAX_CHANNELS} 个")
        
        if len(iptv_list) > 0:
            # 过滤并保存
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

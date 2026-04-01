import time
import requests
import re
import logging
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from FFmpegTest import analyze_iptv_with_ffmpeg


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
            # 保留 IPTV 地址（包括 RTP 组播和普通 HTTP 流）
            if '/rtp/' in line or '239.' in line or '.m3u8' in line or 'live/' in line:
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
    result = analyze_iptv_with_ffmpeg(url, duration)
    
    if not result or not result.get('success'):
        return {'pass': False, 'reason': '分析失败'}
    
    width = result.get('width', 0)
    height = result.get('height', 0)
    speed_mbps = result.get('speed_mbps', 0)
    
    # 判断分辨率是否 >= 1080P (1920x1080)
    resolution_pass = (width >= 1920 and height >= 1080)
    
    # 判断实时带宽是否 > 1MB/s
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

def filter_and_save_playlist(iptv_list, output_file='list.m3u', duration=10, max_workers=5):
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

    def test_single_channel(args):
        """单个频道测试函数"""
        idx, (channel_info, url) = args
        name = channel_info.get('name', '未知')
        start_time = time.time()  # 记录开始时间

        try:
            result = analyze_iptv_with_ffmpeg(url, duration)
            if not result or not result.get('success'):
                return {'index': idx, 'channel_info': channel_info, 'url': url, 'pass': False, 'reason': '分析失败','duration': time.time() - start_time }

            width = result.get('width', 0)
            height = result.get('height', 0)
            speed_mbps = result.get('speed_mbps', 0)

            resolution_pass = (width >= 1920 and height >= 1080)
            bandwidth_pass = speed_mbps >= 1.0
            passed = resolution_pass and bandwidth_pass

            return {
                'index': idx, 'channel_info': channel_info, 'url': url, 'pass': passed,'duration': time.time() - start_time ,
                'test_result': {'resolution': f"{width}x{height}", 'speed_mbps': speed_mbps,
                                'resolution_pass': resolution_pass, 'bandwidth_pass': bandwidth_pass}
            }
        except Exception as e:
            return {'index': idx, 'channel_info': channel_info, 'url': url, 'pass': False, 'reason': str(e),'duration': time.time() - start_time }

    # 开始计时
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # --- 修正1：去掉多余的 enumerate，直接遍历列表 ---
        # item 现在直接是 (index, channel_info)
        futures = {executor.submit(test_single_channel, item): item[0] for item in enumerate(iptv_list, 1)}

        for future in as_completed(futures):
            # 获取该任务对应的原始序号（用于日志排序或追踪，虽然这里没用到排序）
            # original_index = futures[future]

            result = future.result()


            processed += 1
            remaining = total - processed

            # 计算预计剩余时间
            elapsed = time.time() - start_time
            # 防止除以 0
            avg_time_per_item = elapsed / processed if processed > 0 else 0
            estimated_remaining_seconds = avg_time_per_item * remaining

            # 格式化时间
            if estimated_remaining_seconds > 0:
                est_min, est_sec = divmod(int(estimated_remaining_seconds), 60)
                time_str = f"{est_min}分{est_sec}秒"
            else:
                time_str = "计算中..."

            # 安全提取数据，防止 result 结构不对导致报错
            idx = result.get('index', '?')
            channel_info = result.get('channel_info', {})
            url = result.get('url', '')
            name = channel_info.get('name', '未知')

            # 获取耗时，保留2位小数
            cost_time = result.get('duration', 0)
            time_tag = f"[耗时:{cost_time:.2f}s]"

            # 构建日志信息

            # logger.info(f"频道 {name} 测试数据返回: {result}")

            # 1. 处理 "通过" 的情况 (pass == True)
            if result.get('pass'):
                # 正常通过
                test_result = result.get('test_result', {})
                width = test_result.get('resolution', 'N/A')
                speed = test_result.get('speed_mbps', 0)
                status = f"✓ 通过 [分辨率:{width}, 带宽:{speed:.2f}MB/s]"
                filtered_list.append((channel_info, url))

            # 2. 处理 "未通过" 的情况 (pass == False)
            else:
                # 优先从 test_result 中找原因（这是你想要的）
                test_result = result.get('test_result', {})
                if test_result:
                    reasons = []
                    if not test_result.get('resolution_pass'):
                        reasons.append(f"分辨率不足({test_result.get('resolution', 'N/A')})")
                    if not test_result.get('bandwidth_pass'):
                        reasons.append(f"带宽不足({test_result.get('speed_mbps', 0):.2f}MB/s)")
                    status = f"✗ 拒绝 [{', '.join(reasons)}]"

                # 如果没有 test_result，说明是执行过程中出错了
                else:
                    error_reason = result.get('reason', '未知错误')
                    status = f"✗ 执行错误 [原因: {error_reason}]"
                    # 这种严重错误才打 ERROR 级别日志
                    logger.error(f"频道 {name} 执行错误: {error_reason}")

            # 输出详细日志
            progress_info = f"[{processed}/{total}] 剩余: {remaining} | 预计剩余: {time_str} | 频道: {name} | {url} | {time_tag} | {status}"
            logger.info(progress_info)

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
    m3u_url = "http://120.26.145.99:50085/sub?wxfmk4X8=m3u"
    
    # 配置参数
    TEST_DURATION = 10      # 每个频道测试时长（秒）
    MAX_WORKERS = 50         # 最大并发线程数
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

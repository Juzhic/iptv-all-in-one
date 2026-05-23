"""
IPTV 质量筛选 - Flask API 服务器版本
部署到宝塔面板后，通过 HTTP 请求调用
"""
from flask import Flask, request, jsonify, send_file
import os
import json
from datetime import datetime
import threading

# 导入核心功能
from app import (
    fetch_m3u_playlist,
    parse_iptv_addresses,
    filter_and_save_playlist
)

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False
# 配置
DEFAULT_CONFIG = {
    'm3u_url': 'https://gh-proxy.com/https://raw.githubusercontent.com/Guovin/iptv-api/gd/output/result.m3u',
    'test_duration': 30,
    'max_workers': 30,
    'bandwidth_limit_mbps': 50,
    'output_file': 'list.m3u'
}

# 任务状态存储
task_status = {
    'running': False,
    'progress': 0,
    'total': 0,
    'processed': 0,
    'success': 0,
    'message': '空闲'
}
task_lock = threading.Lock()


def update_task_status(**kwargs):
    """线程安全地更新任务状态。"""
    with task_lock:
        task_status.update(kwargs)


def get_task_status_snapshot():
    """线程安全地读取任务状态。"""
    with task_lock:
        return task_status.copy()


def parse_positive_int(value, default, min_value=1, max_value=100):
    """解析接口传入的正整数参数，并限制合理范围。"""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(min_value, min(parsed, max_value))


def parse_nonnegative_float(value, default, max_value=1000):
    """解析接口传入的非负数字参数。"""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0, min(parsed, max_value))


@app.route('/')
def index():
    """API 首页"""
    return jsonify({
        'name': 'IPTV 质量筛选 API',
        'version': '2.0',
        'endpoints': {
            'generate': '/api/generate',
            'status': '/api/status',
            'download': '/api/download',
            'config': '/api/config'
        },
        'description': '自动筛选高质量的 IPTV 频道（1080P + 高带宽）'
    })


@app.route('/api/generate', methods=['POST', 'GET'])
def generate_playlist():
    """
    生成高质量播放列表
    
    GET 参数:
    - m3u_url: M3U 数据源地址（可选，默认使用配置的地址）
    - duration: 每个频道测试时长（秒，可选，默认 30）
    - workers: 并发线程数（可选，默认 5）
    
    POST JSON:
    {
        "m3u_url": "http://...",
        "duration": 30,
        "workers": 5
    }
    """
    global task_status
    
    # 获取参数（支持 GET 和 POST）
    if request.method == 'POST':
        data = request.get_json() or {}
        m3u_url = data.get('m3u_url', DEFAULT_CONFIG['m3u_url'])
        duration = parse_positive_int(data.get('duration'), DEFAULT_CONFIG['test_duration'], max_value=300)
        workers = parse_positive_int(data.get('workers'), DEFAULT_CONFIG['max_workers'], max_value=100)
        bandwidth_limit = parse_nonnegative_float(
            data.get('bandwidth_limit_mbps', data.get('bandwidth_limit')),
            DEFAULT_CONFIG['bandwidth_limit_mbps']
        )
    else:
        m3u_url = request.args.get('m3u_url', DEFAULT_CONFIG['m3u_url'])
        duration = parse_positive_int(request.args.get('duration'), DEFAULT_CONFIG['test_duration'], max_value=300)
        workers = parse_positive_int(request.args.get('workers'), DEFAULT_CONFIG['max_workers'], max_value=100)
        bandwidth_limit = parse_nonnegative_float(
            request.args.get('bandwidth_limit_mbps', request.args.get('bandwidth_limit')),
            DEFAULT_CONFIG['bandwidth_limit_mbps']
        )
    
    output_file = 'latest_list.m3u'  # 使用固定的输出文件名

    with task_lock:
        if task_status['running']:
            return jsonify({
                'error': '已有任务正在运行',
                'status': task_status.copy()
            }), 400

        task_status.update({
            'running': True,
            'progress': 0,
            'total': 0,
            'processed': 0,
            'success': 0,
            'message': '任务已启动'
        })
    
    # 启动后台线程执行任务
    def run_task():
        nonlocal m3u_url, duration, workers, bandwidth_limit, output_file
        
        try:
            update_task_status(message='正在获取 M3U 数据...')
            
            # 获取数据
            m3u_content = fetch_m3u_playlist(m3u_url)
            if not m3u_content:
                update_task_status(message='获取 M3U 数据失败', running=False)
                return
            
            # 解析地址
            iptv_list = parse_iptv_addresses(m3u_content)
            update_task_status(
                total=len(iptv_list),
                message=f'解析到 {len(iptv_list)} 个频道，开始测试...'
            )
            
            if len(iptv_list) == 0:
                update_task_status(message='未解析到任何 IPTV 地址', running=False)
                return

            def on_progress(progress):
                total = progress['total']
                processed = progress['processed']
                percent = round((processed / total) * 100, 1) if total else 0
                update_task_status(
                    progress=percent,
                    total=total,
                    processed=processed,
                    success=progress['success'],
                    message=f"测试中 {processed}/{total}，符合条件 {progress['success']} 个"
                )
            
            filtered_list = filter_and_save_playlist(
                iptv_list,
                output_file,
                duration,
                workers,
                progress_callback=on_progress,
                bandwidth_limit_mbps=bandwidth_limit
            )
            
            update_task_status(
                running=False,
                progress=100,
                processed=len(iptv_list),
                total=len(iptv_list),
                success=len(filtered_list),
                message=f'完成！结果已保存到 {output_file}'
            )
            
        except Exception as e:
            update_task_status(message=f'错误：{str(e)}', running=False)
    
    # 启动线程
    thread = threading.Thread(target=run_task)
    thread.daemon = True
    thread.start()
    
    return jsonify({
        'message': '任务已启动',
        'output_file': output_file,
        'download_url': '/api/download?file=latest_list.m3u',
        'config': {
            'm3u_url': m3u_url,
            'duration': duration,
            'workers': workers,
            'bandwidth_limit_mbps': bandwidth_limit
        }
    })


@app.route('/api/status')
def get_status():
    """获取任务状态"""
    return jsonify(get_task_status_snapshot())


@app.route('/api/download')
def download_file():
    """下载最新的播放列表文件"""
    filename = os.path.basename(request.args.get('file', 'latest_list.m3u'))
    
    if not os.path.exists(filename):
        return jsonify({
            'error': '文件不存在',
            'message': '任务可能还在运行中，请稍后重试'
        }), 404
    
    return send_file(
        filename,
        mimetype='audio/x-mpegurl',
        as_attachment=True,
        download_name='iptv_high_quality.m3u'
    )


@app.route('/list.m3u')
def download_latest_list():
    """直接访问最新播放列表（简化接口）"""
    filename = 'latest_list.m3u'
    
    if not os.path.exists(filename):
        return jsonify({
            'error': '文件不存在',
            'message': '请先运行一次生成任务'
        }), 404
    
    return send_file(
        filename,
        mimetype='audio/x-mpegurl',
        as_attachment=False
    )


@app.route('/api/config')
def get_config():
    """获取当前配置"""
    return jsonify(DEFAULT_CONFIG)


@app.route('/api/health')
def health_check():
    """健康检查"""
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.now().isoformat(),
        'running': task_status['running']
    })


if __name__ == '__main__':
    # 服务器配置
    HOST = os.environ.get('SERVER_HOST', '0.0.0.0')
    PORT = int(os.environ.get('SERVER_PORT', 5000))
    DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'
    
    print("="*60)
    print("IPTV 质量筛选 API 服务器")
    print("="*60)
    print(f"监听地址：http://{HOST}:{PORT}")
    print(f"调试模式：{DEBUG}")
    print("="*60)
    print("\n可用接口:")
    print("  GET  /              - API 信息")
    print("  POST /api/generate  - 生成播放列表")
    print("  GET  /api/status    - 任务状态")
    print("  GET  /api/download  - 下载文件")
    print("  GET  /api/health    - 健康检查")
    print("="*60)
    
    app.run(host=HOST, port=PORT, debug=DEBUG, threaded=True)

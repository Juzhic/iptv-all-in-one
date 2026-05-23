# IPTV 频道质量筛选工具 - 完整使用指南

## 📋 项目简介

自动化的 IPTV 频道质量筛选工具，使用 FFmpeg 分析视频流，筛选出高质量的频道（1080P + 高带宽），支持多线程并发测试。

**核心功能:**
- ✅ 自动获取 M3U 播放列表
- ✅ 智能解析 IPTV 地址（支持 RTP、m3u8、HTTP 流）
- ✅ FFmpeg 专业质量分析
- ✅ 多线程并发测试（速度提升 5-20 倍）
- ✅ Flask API 服务（支持远程调用）
- ✅ 定时任务支持（宝塔面板集成）

---

## 🚀 快速开始

### 本地测试

#### 1. 安装依赖
```bash
pip install -r requirements.txt
```

#### 2. 使用 app.py 本地快速测试
```bash
python app.py
```

### 服务器部署（生产环境）

#### 1. 启动 API 服务
```bash
# 开发环境
python server.py

# 生产环境（推荐）
gunicorn -w 4 -b 0.0.0.0:5000 server:app
```

#### 2. API 调用
```bash
curl -X POST http://localhost:5000/api/generate \
  -H "Content-Type: application/json" \
  -d '{"duration":30,"workers":5}'
```

---

## 📁 文件说明

### 核心程序
- **server.py** - Flask API 服务器（主入口）
- **app.py** - 核心测试逻辑，也可直接运行做本地快速测试
- **FFmpegTest.py** - FFmpeg 测试模块

### 配置文件
- **requirements.txt** - Python 依赖包

### 文档
- **README.md** - 本文件（完整使用指南）
- **DEPLOYMENT.md** - 宝塔面板部署教程
- **SERVER_DEPLOY.md** - 服务器部署检查清单

---

## 🎯 筛选标准

### 质量标准
- **分辨率**: ≥ 1920x1080 (1080P)
- **实时带宽**: > 1 MB/s
- **采样时长**: 30 秒（可配置）
- **码率**: 保留信息（不作为筛选条件）

### 输出格式
生成的 `list.m3u` 文件格式:
```m3u
#EXTM3U x-tvg-url="https://live.fanmingming.cn/e.xml"
#EXTINF:-1 group-title="央视",CCTV1
http://example.com/live/cctv1.m3u8
#EXTINF:-1 group-title="央视",CCTV2
http://example.com/live/cctv2.m3u8
```

---

## 🔧 配置说明

### app.py 配置

```python
# M3U 数据源 URL
m3u_url = "https://gh-proxy.com/https://raw.githubusercontent.com/Guovin/iptv-api/gd/output/result.m3u"

# 性能配置
TEST_DURATION = 30      # 每个频道测试时长（秒）
MAX_WORKERS = 5         # 最大并发线程数
OUTPUT_FILE = 'list.m3u'  # 输出文件名
```

### 性能参考

| 频道数 | workers=5 | workers=10 | workers=20 |
|--------|-----------|------------|------------|
| 10     | 1 分钟    | 0.5 分钟   | 0.25 分钟  |
| 50     | 5 分钟    | 2.5 分钟   | 1.25 分钟  |
| 100    | 10 分钟   | 5 分钟     | 2.5 分钟   |
| 500    | 50 分钟   | 25 分钟    | 12.5 分钟  |

---

## 🌐 API 接口（server.py）

### 基础地址
```
http://服务器IP:5000
```

### 1. 生成播放列表

**POST 请求（推荐）**
```bash
curl -X POST http://localhost:5000/api/generate \
  -H "Content-Type: application/json" \
  -d '{
    "m3u_url": "https://gh-proxy.com/https://raw.githubusercontent.com/Guovin/iptv-api/gd/output/result.m3u",
    "duration": 30,
    "workers": 5
  }'
```

**GET 请求**
```bash
curl "http://localhost:5000/api/generate?duration=30&workers=5"
```

### 2. 查看任务状态
```bash
curl http://localhost:5000/api/status
```

### 3. 下载播放列表
```bash
curl -O http://localhost:5000/api/download?file=list_20260330_120000.m3u
```

或在浏览器打开：
```
http://localhost:5000/api/download?file=list_20260330_120000.m3u
```

### 4. 健康检查
```bash
curl http://localhost:5000/api/health
```

---

## ⏰ 宝塔定时任务配置

### 方案 1: 调用 API（服务常驻）

**计划任务内容:**
```bash
#!/bin/bash
cd /www/wwwroot/iptv-filter

# 每天凌晨 2 点执行
curl -X POST http://127.0.0.1:5000/api/generate \
  -H "Content-Type: application/json" \
  -d '{"m3u_url":"https://gh-proxy.com/https://raw.githubusercontent.com/Guovin/iptv-api/gd/output/result.m3u","duration":30,"workers":5}' \
  > /dev/null 2>&1

# 等待完成
sleep 300

# 复制最新文件
cp list_*.m3u latest_list.m3u 2>/dev/null

echo "IPTV 筛选完成 - $(date)" >> logs/cron.log
```

**执行周期:** 每天 凌晨 2:00

### 方案 2: 直接运行脚本

**计划任务内容:**
```bash
#!/bin/bash
cd /www/wwwroot/iptv-filter
source venv/bin/activate
python app.py >> logs/cron.log 2>&1
```

**执行周期:** 每天 凌晨 2:00

---

## 🛠️ 常见问题

### Q1: 无法获取 M3U 数据
**原因**: 网络不通或服务器不可用  
**解决**: 
```bash
# 测试网络连接
ping gh-proxy.com

# 检查 URL 是否可访问
curl -I https://gh-proxy.com/https://raw.githubusercontent.com/Guovin/iptv-api/gd/output/result.m3u
```

### Q2: FFmpeg 未找到
**原因**: 系统未安装 FFmpeg  
**解决**:
```bash
# CentOS/RHEL
yum install -y ffmpeg

# Ubuntu/Debian
apt-get install -y ffmpeg

# 验证安装
ffmpeg -version
```

### Q3: 所有频道都不符合
**原因**: 筛选条件太严格  
**解决**: 修改 `app.py` 中的判断条件:
```python
# 降低为 720P 和 0.5MB/s
resolution_pass = (width >= 1280 and height >= 720)
bandwidth_pass = speed_mbps > 0.5
```

### Q4: 服务无法启动
**原因**: 端口占用或依赖缺失  
**解决**:
```bash
# 检查端口占用
netstat -tlnp | grep 5000

# 重新安装依赖
pip install -r requirements.txt --force-reinstall
```

### Q5: 内存不足
**原因**: 并发线程数过多  
**解决**:
```python
# 减少并发数到 3-5
MAX_WORKERS = 3
```

---

## 📊 故障排查

### 查看日志
```bash
# 应用日志
tail -f logs/error.log

# 定时任务日志
tail -f logs/cron.log
```

### 资源监控
```bash
# CPU 和内存
top -p $(pgrep -f server.py)

# 磁盘空间
df -h

# 网络连接
netstat -an | grep 5000
```

### 清理旧文件
```bash
# 只保留最近 10 个播放列表
ls -t list_*.m3u | tail -n +11 | xargs rm -f

# 清理日志（保留 7 天）
find logs/ -name "*.log" -mtime +7 -delete
```

---

## 📈 性能优化建议

### 低配服务器（1 核 1GB）
```python
TEST_DURATION = 20      # 缩短测试时间
MAX_WORKERS = 3         # 减少并发
```

### 中等配置（2 核 2GB）
```python
TEST_DURATION = 30      # 标准测试时间
MAX_WORKERS = 5         # 默认并发数
```

### 高配服务器（4 核 4GB+）
```python
TEST_DURATION = 30      # 标准测试时间
MAX_WORKERS = 10        # 增加并发
```

---

## 🔒 安全建议

### 1. 防火墙设置
```bash
# 只允许特定 IP 访问
iptables -A INPUT -p tcp --dport 5000 -s 允许的 IP -j ACCEPT
iptables -A INPUT -p tcp --dport 5000 -j DROP
```

### 2. 添加 API 认证（可选）
在 `server.py` 中添加 token 验证:
```python
@app.before_request
def check_auth():
    if request.endpoint != 'health_check':
        token = request.headers.get('Authorization')
        if token != 'Bearer YOUR_SECRET_TOKEN':
            return jsonify({'error': 'Unauthorized'}), 401
```

### 3. 定期清理
```bash
# 每周清理旧文件
find /www/wwwroot/iptv-filter -name "list_*.m3u" -mtime +7 -delete
```

---

## 📝 部署步骤总结

### 本地测试
1. 安装依赖：`pip install -r requirements.txt`
2. 本地快速测试：`python app.py`

### 服务器部署
1. 上传文件到服务器
2. 安装依赖：`pip install -r requirements.txt`
3. 安装 FFmpeg: `yum install -y ffmpeg`
4. 启动服务：`python server.py` 或 `gunicorn -w 4 -b 0.0.0.0:5000 server:app`
5. 测试 API: `curl http://localhost:5000/api/health`
6. 设置定时任务（可选）

---

## 🎯 下一步

测试成功后，可以将生成的 `list.m3u` 导入到:
- VLC 播放器
- Kodi 媒体中心
- IPTV 播放软件
- 电视盒子

---

## 📞 更多帮助

查看详细部署教程:
- [DEPLOYMENT.md](DEPLOYMENT.md) - 宝塔面板详细教程
- [SERVER_DEPLOY.md](SERVER_DEPLOY.md) - 快速检查清单

---

**祝你使用愉快！🎉**

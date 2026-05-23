# API 使用指南 - IPTV 质量筛选

## 🌐 访问地址

### 基础 URL
```
http://你的服务器IP:5000
```

---

## 📡 快速使用（推荐）

### 1. 生成播放列表
```bash
curl -X POST http://你的IP:5000/api/generate \
  -H "Content-Type: application/json" \
  -d '{"duration":30,"workers":5}'
```

**响应：**
```json
{
  "message": "任务已启动",
  "output_file": "latest_list.m3u",
  "download_url": "/api/download?file=latest_list.m3u",
  "config": {
    "duration": 30,
    "m3u_url": "https://gh-proxy.com/https://raw.githubusercontent.com/Guovin/iptv-api/gd/output/result.m3u",
    "workers": 5
  }
}
```

### 2. 等待任务完成（约 5-10 分钟）
```bash
# 查看任务状态
curl http://你的IP:5000/api/status
```

**响应：**
```json
{
  "running": false,
  "progress": 100,
  "total": 50,
  "processed": 50,
  "success": 12,
  "message": "完成！结果已保存到 latest_list.m3u"
}
```

### 3. 获取最新播放列表

#### 方式 1: 直接访问（最简单）⭐
```
http://你的服务器IP:5000/list.m3u
```

✅ **推荐！** 固定文件名，总是返回最新的播放列表

#### 方式 2: 通过下载接口
```
http://你的服务器IP:5000/api/download?file=latest_list.m3u
```

#### 方式 3: 命令行下载
```bash
curl -O http://你的IP:5000/list.m3u
```

---

## 🔧 完整 API 接口

### 1. 生成播放列表

**POST /api/generate**

```bash
# 使用默认配置
curl -X POST http://你的IP:5000/api/generate

# 自定义配置
curl -X POST http://你的IP:5000/api/generate \
  -H "Content-Type: application/json" \
  -d '{
    "m3u_url": "https://gh-proxy.com/https://raw.githubusercontent.com/Guovin/iptv-api/gd/output/result.m3u",
    "duration": 30,
    "workers": 5
  }'
```

**参数说明：**
- `m3u_url` (可选): M3U 数据源地址，默认使用配置的地址
- `duration` (可选): 每个频道测试时长（秒），默认 30
- `workers` (可选): 并发线程数，默认 5

**响应示例：**
```json
{
  "message": "任务已启动",
  "output_file": "latest_list.m3u",
  "download_url": "/api/download?file=latest_list.m3u",
  "config": {
    "m3u_url": "http://...",
    "duration": 30,
    "workers": 5
  }
}
```

---

### 2. 查看任务状态

**GET /api/status**

```bash
curl http://你的IP:5000/api/status
```

**响应示例：**
```json
{
  "running": false,
  "progress": 100,
  "total": 50,
  "processed": 50,
  "success": 12,
  "failed": 38,
  "message": "完成！结果已保存到 latest_list.m3u"
}
```

**状态字段说明：**
- `running`: 是否正在运行
- `progress`: 进度百分比
- `total`: 总频道数
- `processed`: 已测试数量
- `success`: 符合条件的数量
- `failed`: 不符合/失败的数量
- `message`: 当前状态消息

---

### 3. 下载播放列表

**GET /api/download?file=latest_list.m3u**

```bash
# 下载最新文件
curl -O http://你的IP:5000/api/download?file=latest_list.m3u

# 或在浏览器中打开
http://你的IP:5000/api/download?file=latest_list.m3u
```

**简化接口（推荐）：**
```
http://你的IP:5000/list.m3u
```

---

### 4. 健康检查

**GET /api/health**

```bash
curl http://你的IP:5000/api/health
```

**响应：**
```json
{
  "status": "ok",
  "timestamp": "2026-03-30T20:46:07",
  "running": false
}
```

---

### 5. 查看配置

**GET /api/config**

```bash
curl http://你的IP:5000/api/config
```

**响应：**
```json
{
  "m3u_url": "https://gh-proxy.com/https://raw.githubusercontent.com/Guovin/iptv-api/gd/output/result.m3u",
  "test_duration": 30,
  "max_workers": 5,
  "output_file": "latest_list.m3u"
}
```

---

## 📋 使用流程

### 完整流程示例

```bash
# 1. 启动任务
TASK=$(curl -s -X POST http://你的IP:5000/api/generate)
echo $TASK

# 2. 等待 5 分钟
sleep 300

# 3. 检查状态
STATUS=$(curl -s http://你的IP:5000/api/status)
echo $STATUS

# 4. 下载结果
curl -O http://你的IP:5000/list.m3u

# 5. 查看文件内容
cat list.m3u | head -20
```

---

## ⏰ 宝塔定时任务

### 每天凌晨 2 点自动生成

**计划任务内容：**
```bash
#!/bin/bash

# 调用 API 生成播放列表
curl -X POST http://127.0.0.1:5000/api/generate > /dev/null 2>&1

# 等待 10 分钟让任务完成
sleep 600

# 备份最新文件（保留 7 天）
cp /www/wwwroot/IPTV-Test/latest_list.m3u /www/wwwroot/IPTV-Test/backups/list_$(date +\%Y\%m\%d).m3u

echo "IPTV 更新完成 - $(date)" >> /www/wwwroot/IPTV-Test/logs/cron.log
```

**执行周期：** 每天 凌晨 2:00

---

## 🎯 常用命令速查

### 一键生成并下载
```bash
# 生成
curl -X POST http://localhost:5000/api/generate

# 等待
sleep 300

# 下载
curl -O http://localhost:5000/list.m3u
```

### 查看实时状态
```bash
watch -n 5 'curl -s http://localhost:5000/api/status | jq .'
```

### 检查服务是否运行
```bash
curl http://localhost:5000/api/health
```

---

## 📊 输出文件格式

生成的 `latest_list.m3u` 文件内容：

```m3u
#EXTM3U x-tvg-url="https://live.fanmingming.cn/e.xml"
#EXTINF:-1 group-title="央视",CCTV1
http://example.com/live/cctv1.m3u8
#EXTINF:-1 group-title="央视",CCTV2
http://example.com/live/cctv2.m3u8
#EXTINF:-1 group-title="卫视",湖南卫视
http://example.com/live/hunan.m3u8
```

---

## ⚠️ 注意事项

### 1. 文件覆盖
每次生成任务完成后，`latest_list.m3u` 会被覆盖，只保留最新的结果。

### 2. 任务互斥
同一时间只能运行一个生成任务。如果已有任务在运行，会返回错误：
```json
{
  "error": "已有任务正在运行",
  "status": {...}
}
```

### 3. 超时设置
- 建议每个频道测试 30 秒
- 50 个频道约需 5 分钟（5 线程并发）
- 如果频道很多，建议增加 workers 数量

### 4. 性能建议
| 频道数 | 推荐 workers | 预计时间 |
|--------|-------------|----------|
| 10-50  | 5           | 1-5 分钟 |
| 50-100 | 10          | 5-10 分钟 |
| 100-500| 15-20       | 10-30 分钟 |

---

## 🔍 故障排查

### 问题 1: 文件不存在
```bash
# 检查任务是否完成
curl http://localhost:5000/api/status

# 如果还在运行，等待完成后再下载
```

### 问题 2: 任务一直运行中
```bash
# 查看进程
ps aux | grep python

# 重启服务（宝塔面板操作）
```

### 问题 3: 所有频道都不符合
检查筛选条件是否太严格，可以修改 `app.py` 中的判断逻辑。

---

## 📞 更多帮助

查看完整文档：[README.md](README.md)

---

**祝你使用愉快！🎉**

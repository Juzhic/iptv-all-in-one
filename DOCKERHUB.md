# iptv-all-in-one

从多个 M3U 订阅源中筛选可用且质量较高的 IPTV 频道，支持 FFmpeg 分辨率检测、带宽测速、频道别名归一、模板化输出、Web 后台配置、历史记录和定时运行。

集成 IPTV 频道扫描模块，可通过搜索引擎 API（Quake / Hunter / DayDayMap / Fofa）自动发现酒店 IPTV 服务器，提取频道列表并送入测速流水线。

## 快速开始

```yaml
# docker-compose.yml
services:
  app:
    image: <your-username>/iptv-all-in-one:latest
    ports:
      - "58080:58080"
    env_file: .env
    depends_on:
      - mysql
    restart: unless-stopped

  mysql:
    image: mysql:8.4
    env_file: .env
    volumes:
      - mysql_data:/var/lib/mysql
    restart: unless-stopped

volumes:
  mysql_data:
```

```bash
# .env
DB_HOST=mysql
DB_PORT=3306
DB_USER=root
DB_PASSWORD=<your-random-password>
DB_NAME=iptv-all-in-one
```

```bash
docker compose up -d
```

访问 `http://localhost:58080` 进入 Web 管理后台。首次启动会在日志中输出随机生成的 BasicAuth 密码，也可通过环境变量 `IPTV_AUTH_PASSWORD` 预设。

## 主要功能

**测速模块**
- 聚合多个 M3U 订阅源，按频道模板精准匹配
- FFmpeg 分辨率检测 + 带宽采样测速
- H.265/HEVC 编码带宽折算
- 频道别名归一（精确 + 正则）
- 定时运行（once / times / interval 三种模式）
- 实时写入 TXT / M3U 输出文件

**扫描模块**
- Quake / Hunter / DayDayMap / Fofa 四平台扫描
- 多 Key 轮换 + 积分余额查询
- 质量优先画像查询（txiptv_live / live_interface / zhgx / tvheadend 等）
- C 段扩展扫描 + 质量热点补源
- 省份 / 城市 / 运营商过滤
- 扫描收益统计（按平台/画像维度）

**检测与运维**
- 持久化结果定期检测，自动移除失效频道
- 检测概览 + 轮次状态 + 质量分档
- SSE 实时进度推送 + 短轮询降级
- MySQL 数据存储，自动重连 + 启动重试
- Docker Compose 内置 MySQL 8.4，开箱即用
- 低内存调优参数，适配小内存服务器

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DB_HOST` | MySQL 主机 | (读取 db_config.json) |
| `DB_PORT` | MySQL 端口 | 3306 |
| `DB_USER` | MySQL 用户 | root |
| `DB_PASSWORD` | MySQL 密码 | (必填) |
| `DB_NAME` | 数据库名 | iptv-all-in-one |
| `IPTV_AUTH_PASSWORD` | Web 后台密码 | (随机生成) |
| `FFMPEG_BIN` | FFmpeg 路径 | /usr/bin/ffmpeg |

## 技术栈

Python 3.12 / Flask / Gunicorn / aiohttp / pymysql / Vue 3 / TDesign / Vite / MySQL 8.4 / FFmpeg / Docker Compose

---

## 更新日志

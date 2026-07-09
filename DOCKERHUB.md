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
| `IPTV_HEALTH_DETAILED` | 健康检查详细模式 | 0 |

## 更新日志

### v1.7.18 (2026-07-09)

**修复**
- 修复扫描配置页"刷新余额"功能失效：前端余额查询失败时静默无反馈，Key 列表停留在"加载中..."。现在失败时显示"余额查询失败"状态并弹出提示。
- 后端 `/api/scan/keys/credits` 增加 50 秒超时保护，防止平台 API 响应慢时无限等待。

**改进**
- 数据库连接失败自动重试 5 次（间隔 3s），适配 Docker 启动时 MySQL 未就绪；认证错误和数据库不存在不重试。
- 应用启动不再因数据库暂时不可用而崩溃，等待首次请求时自动重试连接。
- 增强 Quake/Hunter API 积分查询健壮性：兼容字段缺失/改名，增加 DEBUG 原始响应日志。
- Fofa 显示"不支持余额查询"，DayDayMap 显示"Key有效 (余额需登录查看)"。

### v1.7.17 (2026-07-07)

**修复**
- 修复"刷新余额"按钮报错：`/api/scan/keys/credits` 缺少 `_ensure_scan_bridge()` 导致 `scanner` 变量未定义。

### v1.7.15 (2026-07-05)

**修复**
- API Key 管理接口返回完整 key 值，修复编辑 Key 时后缀匹配失败导致无法保存。
- 修复测试日志混入其他模块日志，`_DBLogHandler` 改用专用 logger。
- 修复测试结束后前端持续轮询 `/progress`、UI 假显示"运行中"。

**改进**
- 测试进度增加数据源来源统计（订阅源 / 扫描源数量）。

### v1.7.13 (2026-07-02)

**改进**
- SSE 端点增加 30 分钟最大连接时长。
- MySQL 连接增加自动重连（2006/2013/2014）。
- `asyncio.run()` 替换为 `scanner.bridge.run_sync()`。
- 前端构建增加超时保护，锁定所有依赖版本。

### v1.7.0 (2026-06-28)

**新增**
- 测绘平台/画像收益统计表，记录每轮扫描的平台、画像、省份维度产出数据。
- 扫描配置新增深度检测参数（时长、采样、超时）。

### v1.6.15 (2026-06-27)

**安全**
- 移除 Docker Compose 默认弱密码，`DB_PASSWORD` 未设置时拒绝启动。
- 新增 `generate_env.py` 自动生成随机密码。

### v1.6.12 (2026-06-27)

**运维**
- Docker Compose 内置 MySQL 启用低内存调优参数，降低小服务器基础占用。

### v1.6.5 (2026-06-26)

**新增**
- 质量优先查询：在基础搜索外追加高价值画像查询。
- 质量热点补源：基于历史频道稳定性识别高价值网段。
- Docker Compose 内置 MySQL 8，开箱即用。

### v1.5.0 (2026-06-21)

**新增**
- 集成 Quake / Hunter / DayDayMap / Fofa 扫描模块。
- C 段扩展扫描、省份/运营商过滤、定时健康检测。

### v1.3.0 (2026-06-19)

**新增**
- Flask Web 后台 + Vue 3 + TDesign 前端。
- 总览、历史明细、系统配置、频道扫描等标签页。
- BasicAuth 认证保护、深色/浅色主题切换。

完整变更记录请查看仓库中的 CHANGELOG.md。

## 技术栈

- **后端**: Python 3.12 / Flask / Gunicorn / aiohttp / pymysql
- **前端**: Vue 3 / TDesign / Vite
- **数据库**: MySQL 8.4
- **媒体**: FFmpeg
- **部署**: Docker / Docker Compose

# IPTV 频道质量筛选工具

从多个 M3U 订阅源中筛选可用且质量较高的 IPTV 频道，支持 FFmpeg 分辨率检测、带宽测速、频道别名归一、模板化输出、Web 后台配置、历史记录和定时运行。

集成 IPTV 频道扫描模块，可通过搜索引擎 API（Quake/Hunter/DayDayMap/Fofa）自动发现酒店 IPTV 服务器，提取频道列表并送入测速流水线。

## 当前版本说明（v1.6.2）

本项目当前以 MySQL 作为主要数据存储，数据库配置位于 `database/db_config.json`。

旧版 README 中提到的 `config.json`、`subscribe.txt`、`alias.txt`、`demo.txt` 已不再作为日常配置入口。现在请通过 Web 后台的"系统配置"页面维护：

| 数据 | 当前存储位置 | 说明 |
| --- | --- | --- |
| 系统参数 | MySQL `config_data` 表，key 为 `config` | 测速时长、并发数、分辨率阈值、运行模式等 |
| 订阅源 | `config_data` 表，key 为 `subscribe` | 每行一个 M3U 地址 |
| 频道模板 | `config_data` 表，key 为 `demo` | 决定要匹配、测速和输出哪些频道 |
| 别名映射 | `config_data` 表，key 为 `alias` | 将不同频道名归一到模板中的主名 |
| 扫描配置 | `config_data` 表，key 为 `scan_config` | 扫描模块的 API Key、平台、省份等配置 |
| 测速历史 | `runs`、`run_results` | 最近运行结果和每个频道 URL 的测速详情 |
| 扫描历史 | `scan_runs`、`scan_results` | 扫描任务记录和扫描到的频道数据 |
| 运行日志 | `run_logs` | 每轮任务日志 |
| 运行进度 | `run_progress` | Web 页面实时进度 |
| 扫描进度 | `scan_progress` | 扫描实时进度 |
| 检测日志 | `detection_logs` | 定期检测模块日志 |
| 持久化结果 | `persistent_scan_results` | 扫描结果持久化存储，支持自动复活机制 |
| IP扫描记录 | `ip_scan_runs`、`ip_scan_results` | IP扫描任务和结果 |
| IP扫描日志 | `ip_scan_logs` | IP扫描日志 |

如果根目录存在旧的 `config.json`，程序首次启动且数据库里没有系统配置时，会尝试迁移到 MySQL，并把原文件重命名为 `config.json.bak`。旧的 `output/history.json` 也会迁移到 MySQL，并重命名为 `.bak`。

## 功能

### 测速模块

- 聚合多个 M3U 订阅源并解析频道地址。
- 按频道模板只测试需要的频道，避免全量盲测。
- 支持精确别名和 `re:` 正则别名，统一不同源里的频道名称。
- 使用 FFmpeg 检测分辨率、编码信息，并结合下载采样计算带宽。
- 支持最低分辨率、最低带宽、H.265 带宽折算、单频道输出数量限制。
- 测速通过后实时写入 `output/result.txt` 和 `output/result.m3u`。
- Web 后台支持配置编辑、手动触发、进度查看、历史查看、日志查看、结果下载。
- 支持 `once`、`times`、`interval` 三种运行模式。
- 频道自动发现：从订阅源中自动发现可用频道，支持分类和模板匹配。
- Webhook 通知：测速完成后支持通过 Webhook 发送通知（支持 Telegram、企业微信等）。
- 质量评分系统：基于带宽和延迟计算频道质量分数，用于排序和筛选。

### 扫描模块

- 通过搜索引擎 API（Quake 360、Hunter 鹰图、DayDayMap、Fofa）自动发现酒店 IPTV 服务器。
- 四平台默认搜索使用 OR 组合查询，一次扫描覆盖多个 IPTV 系统特征（`/iptv/live/zh_cn.js`、`1000.json?key=txiptv`、`ZHGXTV`、`jsmpeg-streamer`、`IPTV互动电视系统`、`EasyLive`、`Hybroad`、`udpxy`、`tvheadend`、`Xtream` 等）。
- 支持 ZHGXTV、JSMpeg、Tvheadend、IPTV互动、EasyLive、Hybroad、udpxy、Xtream 等多种 IPTV 系统的独立扫描和频道提取。
- C 段扫描：对已发现的 IP 所在 /24 子网进行扩展扫描，支持智能采样和限制。
- 快速过滤（HEAD 请求验证）+ 深度检测（带宽/延迟/稳定性/分辨率）。
- 轻量级 H.264 分辨率解析：无需调用 ffprobe，直接解析 TS 流获取分辨率。
- 自动频道名归一和分类（央视频道、卫视频道、各省频道）。
- 省份/城市/运营商过滤。
- 健康检查增强：FFmpeg/磁盘/内存/扫描模块检查，版本和运行时间信息。
- 扫描结果可选择性送入测速流水线，经 FFmpeg 深度检测后输出。
- 定期检测模块：自动检测已发现频道的可用性，连续失败达到阈值自动移除。
- 频道复活机制：定期尝试复活已删除的频道，避免误删。
- ISP 情报分析：分析历史扫描数据，发现 IPTV 密集的 IP 段进行主动扫描。
- 社区源聚合：从 GitHub 上的公开 IPTV M3U 仓库采集频道列表。
- 域名扫描：支持 DNS/Censys/RapidDNS/crt.sh 域名扫描发现 IPTV 服务。
- API Key 多 Key 轮转：支持 Quake/Hunter/DayDayMap/Fofa 多 Key 轮转，避免单 Key 限流。
- 稳定性评分：基于带宽、卡顿、抖动、空包率、延迟等多维度计算频道稳定性。
- SSE 实时推送：扫描日志和检测日志通过 SSE 实时推送到前端。

### IP 扫描模块

- 支持批量 IP/域名输入，可指定端口或使用预设端口组。
- 多种 IPTV 系统自动检测：ZHGXTV、JSMpeg、Tvheadend、udpxy、Xtream 等。
- 自动提取频道列表并支持送入测速流水线。
- 支持端口预设：常用端口、IPTV 专用端口、全部端口等。
- 扫描结果持久化存储，支持历史记录查看。

### Web 后台

- Flask Web 后台，提供完整的 RESTful API 接口。
- Vue 3 + TDesign 前端界面，支持深色/浅色主题切换。
- 9 个功能标签页：总览、历史明细、系统测试、系统配置、频道扫描、扫描配置、检测监控、扫描结果、IP扫描。
- BasicAuth 认证保护，支持环境变量和配置文件两种方式。
- Vite 开发模式，支持前端热更新。
- 键盘快捷键支持：Ctrl+S 保存、Ctrl+F 搜索、Alt+1-9 切换标签页。
- 无障碍访问 (a11y) 支持：语义化标签、ARIA 属性、焦点管理。
- 操作确认弹窗：终止测试、停止扫描、强制清除、清空日志等危险操作需确认。
- 表单即时验证反馈。
- 统一 API 响应格式：`{'ok': True/False, 'data': ...}`。
- 全局错误处理器：404/500/405 返回 JSON 而非 HTML。
- 分页参数上限校验（最大 200 条）。
- 前端轮询优化：指数退避和 Tab 可见性感知。

### 数据库层

- MySQL 数据库存储，通过 `database/db_config.json` 配置连接信息。
- 数据库自动迁移：首次启动自动迁移旧版 config.json 和 history.json。
- 日志批量写入：减少 commit 次数，提高性能。
- 日志保留策略：测速日志 30 天、扫描日志 7 天、持久化结果 90 天、质量历史 90 天。
- 数据库最多保留最近 50 轮历史记录。
- 复合索引和唯一约束优化查询性能。
- 线程安全的写入锁保护并发写入。

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

系统还需要安装 FFmpeg，并确保 `ffmpeg` 在 `PATH` 中。也可以通过环境变量 `FFMPEG_BIN` 指定可执行文件路径。

前端使用 Vue 3 + TDesign 组件库，需要 Node.js 18+ 环境。首次使用或前端代码有变动时需重新构建：

```bash
cd frontend
npm install    # 首次安装依赖
npm run build  # 构建前端，输出到 dist/
cd ..
```

### 2. 配置数据库

复制数据库配置示例文件并填写 MySQL 连接信息：

```bash
cp database/db_config.json.example database/db_config.json
```

编辑 `database/db_config.json`：

```json
{
    "host": "127.0.0.1",
    "port": 3306,
    "user": "your_username",
    "password": "your_password",
    "database": "iptv-test",
    "charset": "utf8mb4"
}
```

### 3. 启动 Web 后台

```bash
python -m web
```

默认访问地址：

```text
http://localhost:58080
```

可通过环境变量 `IPTV_HOST` 和 `IPTV_PORT` 自定义监听地址和端口：

```bash
# Linux/macOS
export IPTV_HOST=127.0.0.1
export IPTV_PORT=8080
python -m web

# Windows PowerShell
$env:IPTV_HOST="127.0.0.1"
$env:IPTV_PORT="8080"
python -m web
```

**开发模式**（前端修改自动热更新，无需手动构建）：

```bash
python -m web --dev
```

此模式下 Vite 开发服务器启动在 `http://localhost:3000`，API 请求自动代理到 Flask 后端。修改 Vue 源码后浏览器即时刷新，无需手动 `npm run build`。

BasicAuth 保护 Web 后台和 API。凭据从程序目录的 `basic_auth.json` 读取：

```json
{
  "username": "admin",
  "password": "admin",
  "realm": "IPTV Test"
}
```

如果文件缺失或无效，使用默认账号 `admin` / `admin`。首次启动时检测到默认密码会在日志中输出安全警告，建议立即修改。

结果订阅下载保持公开：`/api/download/txt` 和 `/api/download/m3u`。

开发模式下，Vite 代理也会自动读取同一份 `basic_auth.json` 并转发 BasicAuth 头，因此 `http://localhost:3000` 下的总览、历史、扫描等 API 页面可直接调试。

Web 服务默认使用 `58080` 端口。如果端口已被旧进程占用，启动会失败并提示先结束占用进程。可通过环境变量 `IPTV_PORT` 更改端口。

启动后进入"系统配置"页，依次填写或调整：

1. 订阅源：每行一个 M3U 地址。
2. 频道模板：需要输出的频道和分类。
3. 别名映射：把源里的不同频道名映射为模板主名。
4. 参数配置：分辨率、带宽、并发数、运行模式等。

保存后可以在页面中手动触发一次测速。

### 4. 使用扫描模块

进入"频道扫描"标签页：

1. 配置 API Key（Quake/Hunter/DayDayMap/Fofa 至少一个）。
2. 选择要扫描的省份（可多选，留空表示全国）。
3. 点击"开始扫描"。
4. 扫描完成后，切换到"扫描结果"标签页查看频道列表。
5. 勾选需要的频道，点击"送入选中去测速"，频道将进入测速流水线。

### 5. 使用 IP 扫描模块

进入"IP扫描"标签页：

1. 输入目标 IP/域名列表（每行一个），支持 `IP:PORT` 格式或纯 IP/域名。
2. 选择端口预设或自定义端口。
3. 选择扫描类型（全部扫描或特定 IPTV 系统）。
4. 点击"开始扫描"。
5. 扫描完成后可查看结果并送入测速流水线。

### 6. 命令行运行

也可以直接运行核心任务：

```bash
python -m engine.test_engine
```

命令行同样会从 MySQL 数据库读取配置，不再读取 `subscribe.txt`、`alias.txt`、`demo.txt`。

## 生产部署

### 方式一：直接运行（开发/测试环境）

```bash
python -m web
```

适合个人使用或小规模部署。Flask 自带的开发服务器仅用于调试，不建议在生产环境使用。

### 方式二：Gunicorn（Linux 推荐）

1. 安装 Gunicorn：

```bash
pip install gunicorn
```

2. 启动服务：

```bash
gunicorn -w 4 -b 0.0.0.0:58080 --timeout 120 web:app
```

参数说明：
- `-w 4`：4 个工作进程（建议 CPU 核心数 × 2 + 1）
- `-b 0.0.0.0:58080`：监听所有网卡的 58080 端口（可通过 `IPTV_PORT` 环境变量更改）
- `--timeout 120`：请求超时 120 秒（测速任务耗时较长）

可通过环境变量自定义配置：

```bash
# 自定义端口
IPTV_PORT=8080 gunicorn -w 4 -b 0.0.0.0:8080 --timeout 120 web:app
```

3. 使用 Systemd 打包为服务（可选）：

创建 `/etc/systemd/system/iptv-test.service`：

```ini
[Unit]
Description=IPTV Test Service
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/path/to/IPTV-Test
ExecStart=/path/to/venv/bin/gunicorn -w 4 -b 127.0.0.1:58080 --timeout 120 web:app
Restart=always
RestartSec=5
Environment="FFMPEG_BIN=/usr/bin/ffmpeg"
Environment="IPTV_AUTH_USERNAME=admin"
Environment="IPTV_AUTH_PASSWORD=your_secure_password"

[Install]
WantedBy=multi-user.target
```

启用并启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable iptv-test
sudo systemctl start iptv-test
```

### 方式三：Nginx 反向代理

在 `/etc/nginx/conf.d/iptv-test.conf` 中添加：

```nginx
server {
    listen 80;
    server_name your-domain.com;

    # 基本认证（可选，推荐配合 basic_auth.json 使用）
    # auth_basic "IPTV Test";
    # auth_basic_user_file /etc/nginx/.htpasswd;

    location / {
        proxy_pass http://127.0.0.1:58080;  # 如果修改了 IPTV_PORT，这里也要对应修改
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300;
        proxy_connect_timeout 60;
    }

    # WebSocket 支持（开发模式热更新）
    location /ws {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### 方式四：Docker 部署（推荐）

项目已包含 `Dockerfile` 和 `docker-compose.yml`，可直接使用：

```bash
# 构建并运行
docker-compose up -d

# 或手动构建
docker build -t iptv-test .
docker run -d \
  --name iptv-test \
  -p 58080:58080 \
  -v $(pwd)/database/db_config.json:/app/database/db_config.json \
  -v $(pwd)/output:/app/output \
  -v $(pwd)/basic_auth.json:/app/basic_auth.json \
  -e FFMPEG_BIN=/usr/bin/ffmpeg \
  -e PYTHONUNBUFFERED=1 \
  iptv-test
```

如需自定义端口和认证，可通过环境变量设置：

```bash
docker run -d \
  --name iptv-test \
  -p 8080:8080 \
  -e IPTV_PORT=8080 \
  -e IPTV_AUTH_USERNAME=myuser \
  -e IPTV_AUTH_PASSWORD=mypassword \
  -v $(pwd)/database/db_config.json:/app/database/db_config.json \
  -v $(pwd)/output:/app/output \
  iptv-test
```

使用 docker-compose.yml 自定义端口：

```bash
# .env 文件
IPTV_PORT=8080

# 或直接指定
IPTV_PORT=8080 docker-compose up -d
```

### 环境变量

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `FFMPEG_BIN` | FFmpeg 可执行文件路径 | `ffmpeg`（从 PATH 查找） |
| `IPTV_HOST` | Web 服务监听地址 | `0.0.0.0` |
| `IPTV_PORT` | Web 服务端口 | `58080` |
| `IPTV_AUTH_USERNAME` | BasicAuth 用户名（覆盖配置文件） | `admin` |
| `IPTV_AUTH_PASSWORD` | BasicAuth 密码（覆盖配置文件） | `admin` |
| `IPTV_AUTH_REALM` | BasicAuth 领域名称（覆盖配置文件） | `IPTV Test` |
| `PYTHONUNBUFFERED` | 禁用 Python 输出缓冲 | 未设置 |
| `MAX_FFMPEG_WORKERS` | FFmpeg 最大并发数（覆盖配置文件） | 未设置 |
| `CENSYS_API_ID` | Censys API ID（域名扫描用） | 未设置 |
| `CENSYS_API_SECRET` | Censys API Secret（域名扫描用） | 未设置 |

### 安全建议

1. **修改默认密码**：编辑 `basic_auth.json`，修改 `username` 和 `password`。首次启动时检测到默认密码会在日志中输出安全警告。
2. **限制访问**：通过防火墙或 Nginx 限制来源 IP
3. **HTTPS**：生产环境务必使用 HTTPS（可通过 Nginx + Let's Encrypt 配置）
4. **数据库备份**：定期备份 MySQL 数据库
5. **凭证管理**：`basic_auth.json` 和 `database/db_config.json` 包含敏感信息，生产环境建议：
   - 通过环境变量传递 BasicAuth 凭证：`IPTV_AUTH_USERNAME`、`IPTV_AUTH_PASSWORD`、`IPTV_AUTH_REALM`
   - `basic_auth.json` 和 `database/db_config.json` 已加入 `.gitignore`，避免意外提交
   - 使用 Docker volumes 挂载而非复制到镜像中

### 目录结构要求

部署时需确保以下目录可写：

```text
database/           # db_config.json 必须存在且可读
output/             # 测速结果输出（运行时自动创建）
dist/               # 前端构建产物（需提前 npm run build）
```

### 常见部署问题

**Q: 启动后页面 404？**
确保已构建前端：`cd frontend && npm run build`，`dist/` 目录存在且包含 `index.html`。

**Q: 端口被占用？**
使用 `lsof -i :58080`（Linux）或 `netstat -ano | findstr :58080`（Windows）查看占用进程并结束。如果需要使用其他端口，可通过环境变量 `IPTV_PORT` 指定。

**Q: Gunicorn 启动失败？**
检查 Python 路径是否正确，确保虚拟环境已激活。可先用 `python -m web` 测试基础功能。

**Q: 数据库连接失败？**
检查 `database/db_config.json` 配置是否正确，确保 MySQL 服务已启动且可访问。

## 系统参数

默认参数定义在 `engine/test_engine.py` 的 `DEFAULT_CONFIG` 中，保存后会写入数据库。

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `test_duration` | `15` | 单个频道地址测速时长，单位秒 |
| `max_workers` | `30` | 最大并发测试线程数 |
| `max_ffmpeg_workers` | `6` | FFmpeg 最大并发数 |
| `system_bandwidth_limit_MBps` | `50` | 系统下行带宽限制，超过后暂停启动新测试；`0` 表示关闭 |
| `system_memory_limit_percent` | `85` | 系统内存使用上限百分比 |
| `min_bandwidth_MBps` | `1.0` | 频道最低带宽要求，单位 MB/s |
| `bandwidth_compensation_MBps` | `2.0` | 未获取到分辨率时的带宽补偿阈值 |
| `h265_bandwidth_ratio` | `0.6` | H.265/HEVC 编码带宽阈值折算比例 |
| `max_urls_per_channel` | `10` | 每个频道最多输出地址数；`0` 表示不限制 |
| `show_update_time` | `true` | 是否在输出结果中加入更新时间 |
| `update_time_position` | `top` | 更新时间位置，支持 `top` 或 `bottom` |
| `min_width` | `1920` | 最低分辨率宽度 |
| `min_height` | `1080` | 最低分辨率高度 |
| `output_txt` | `output/result.txt` | TXT 输出路径 |
| `output_m3u` | `output/result.m3u` | M3U 输出路径 |
| `run_mode` | `once` | 运行模式：`once`、`times`、`interval` |
| `run_times` | `[]` | `times` 模式下的执行时间列表，例如 `06:00,12:00,18:00` |
| `run_interval_minutes` | `60` | `interval` 模式下的执行间隔，单位分钟 |
| `logo_base_url` | `https://www.xn--rgv465a.top/tvlogo` | M3U 文件中频道 logo 图片的基础 URL |
| `epg_url` | `""` | EPG 电子节目单地址 |
| `include_scan_results_in_test` | `false` | 测速时是否包含扫描结果中的频道 |
| `webhook_enabled` | `false` | 是否启用 Webhook 通知 |
| `webhook_url` | `""` | Webhook 通知 URL |
| `webhook_on_test` | `true` | 测速完成时是否发送 Webhook 通知 |
| `webhook_on_scan` | `true` | 扫描完成时是否发送 Webhook 通知 |
| `webhook_on_detection` | `true` | 检测完成时是否发送 Webhook 通知 |

## 文本配置格式

这些内容现在都在 Web 后台编辑，保存后写入 MySQL 数据库。

### 订阅源

每行一个 M3U 地址，空行和 `#` 开头的注释行会被忽略。

```text
https://example.com/playlist1.m3u
https://example.com/playlist2.m3u
```

### 别名映射

每行一个主名映射，第一列是主名，后续列是别名。以 `re:` 开头的别名会按正则表达式匹配。

```text
CCTV-1,re:(?i)^\s*CCTV[-\s_]*0?1(?![0-9Kk+])[\s\S]*$,CCTV1,CCTV-01,CCTV-1综合
CCTV-5+,re:(?i)^\s*CCTV[-\s_]*0?5\s*(?:\+|PLUS)[\s\S]*$,CCTV5+,CCTV-5+体育赛事
```

模板中的频道名建议使用主名。源里的频道名命中别名后，会统一归一到主名参与匹配和输出。

### 频道模板

包含 `,#genre#` 的行是分类标题，其他行是频道主名。只有模板中出现的频道才会被匹配、测速和输出。

```text
央视频道,#genre#
CCTV-1
CCTV-5
CCTV-5+

卫视频道,#genre#
广东卫视
浙江卫视
湖南卫视
```

频道模板为空时不会执行有效测速。

## 输出结果

每轮任务会把通过筛选的地址写入：

```text
output/result.txt
output/result.m3u
```

Web 后台的下载接口会根据数据库中最近一轮通过的结果动态生成文件：

```text
/api/download/txt
/api/download/m3u
```

测速历史、详情、日志和实时进度保存在 MySQL 数据库中，不再依赖 `output/history.json`。当前数据库最多保留最近 50 轮历史记录。日志保留策略：测速日志 30 天、扫描日志 7 天、持久化结果 90 天、质量历史 90 天。

### 输出格式

**TXT 格式**（`output/result.txt`）：
```text
央视频道,#genre#
CCTV-1,http://example.com/stream1.m3u8
CCTV-2,http://example.com/stream2.m3u8

卫视频道,#genre#
广东卫视,http://example.com/stream3.m3u8
```

**M3U 格式**（`output/result.m3u`）：
```m3u
#EXTM3U x-tvg-url="http://epg.example.com"
#EXTINF:-1 tvg-name="CCTV-1" tvg-logo="http://logo.example.com/cctv1.png" group-title="央视频道",CCTV-1
http://example.com/stream1.m3u8
#EXTINF:-1 tvg-name="CCTV-2" tvg-logo="http://logo.example.com/cctv2.png" group-title="央视频道",CCTV-2
http://example.com/stream2.m3u8
```

### 质量评分

每个频道的质量评分基于带宽和延迟计算：
- 评分公式：`bandwidth / (1 + latency_seconds)`
- 带宽越高、延迟越低，评分越高
- 评分用于频道内 URL 排序和筛选

## 运行模式

### `once`

只手动触发或命令行运行一次。Web 服务启动时不会自动开始测速。

### `times`

按照指定时间点循环运行，例如：

```json
{
  "run_mode": "times",
  "run_times": ["06:00", "12:00", "18:00"]
}
```

### `interval`

按间隔循环运行，例如：

```json
{
  "run_mode": "interval",
  "run_interval_minutes": 120
}
```

## 项目结构

```text
IPTV-Test/
├── web/                        # Flask Web 后台和 API（唯一根入口）
│   ├── __init__.py             # 包入口，创建 Flask app（gunicorn web:app）
│   ├── __main__.py             # python -m web 启动入口
│   ├── app.py                  # Flask 应用工厂、BasicAuth 中间件、前端自动构建
│   ├── routes/                 # API 路由模块
│   │   ├── __init__.py         # 蓝图注册入口
│   │   ├── config.py           # 配置管理 API
│   │   ├── download.py         # 文件下载 API
│   │   ├── health.py           # 健康检查 API
│   │   ├── history.py          # 历史记录 API
│   │   ├── ip_scan.py          # IP 扫描 API
│   │   ├── scan.py             # 扫描控制 API
│   │   ├── spa.py              # SPA 静态文件服务
│   │   ├── subscribe.py        # 订阅源 API
│   │   └── test_control.py     # 测试控制 API
│   ├── scheduler.py            # 定时任务调度器
│   ├── state.py                # 全局状态管理
│   ├── result_gen.py           # 结果文件生成
│   └── test_runner.py          # 测速任务运行器
│
├── database/                   # 数据库层
│   ├── __init__.py             # 统一导出所有数据库接口
│   ├── db.py                   # MySQL 表结构、配置、历史、日志和进度存取
│   ├── db_config.json          # MySQL 连接配置（gitignore）
│   └── db_config.json.example  # 数据库配置示例
│
├── engine/                     # 测速引擎核心
│   ├── __init__.py             # 统一导出引擎接口
│   ├── test_engine.py          # 核心测速引擎：频道匹配、M3U 源解析、测速编排、输出生成
│   ├── ffmpeg_test.py          # FFmpeg 分析、带宽采样和 HTTP 拉流检测
│   ├── alias.py                # 共享别名模块（测速和扫描共用）
│   ├── discovery.py            # 频道发现：从扫描结果中提取和过滤频道
│   ├── notifications.py        # 通知模块：Webhook 通知（支持 SSRF 防护）
│   └── utils.py                # 共享工具函数（安全数值转换等）
│
├── scanner_integration/        # 扫描模块
│   ├── __init__.py             # 异步桥接、扫描编排、SSE 推送、定时任务入口
│   ├── config_bridge.py        # 扫描配置读写
│   ├── key_manager.py          # API Key 管理（Quake/Hunter/DayDayMap/Fofa 多 Key 轮转）
│   ├── platforms.py            # 平台扫描（Quake/Hunter/DayDayMap/Fofa/ZHGXTV/JSMpeg/Tvheadend/DDGS 等）
│   ├── video_check.py          # 流验证：快速过滤、深度检测、轻量级 H.264 分辨率解析
│   ├── channel_utils.py        # 频道名归一、分类、黑名单过滤
│   ├── community_sources.py    # 社区源：从 GitHub 公开 IPTV 源获取频道
│   ├── isp_intelligence.py     # ISP 情报：分析历史数据发现热点 IP 段
│   ├── network.py              # 异步 HTTP 会话、全局信号量、快速 HTTP 检查
│   ├── geo_data.py             # 地理数据、省份检测
│   ├── province_cities.py      # 省市频道映射
│   ├── domain_ip_scanner.py    # DNS/Censys/RapidDNS/crt.sh 域名扫描
│   ├── ip_scanner.py           # IP 扫描引擎：批量 IP/域名扫描、多 IPTV 系统检测
│   ├── ip_scan_types.py        # IP 扫描类型定义：扫描路径和端口配置
│   ├── persistence.py          # 扫描结果持久化合并
│   ├── detection.py            # 定期检测：自动移除失效频道、频道复活机制
│   ├── logger_bridge.py        # 日志模块
│   └── pca-code.json           # 行政区划数据
│
├── frontend/                   # Vue 3 前端源码（TDesign Vue Next）
│   ├── index.html              # SPA 入口
│   ├── package.json            # 前端依赖和构建脚本
│   ├── vite.config.js          # Vite 构建配置（含开发代理）
│   ├── node_modules/           # npm 依赖（gitignore）
│   └── src/
│       ├── main.js             # Vue 应用初始化
│       ├── api.js              # 统一 API 请求封装
│       ├── App.vue             # 根组件：布局、头部、标签页
│       ├── components/
│       │   ├── OverviewTab.vue # 总览：统计卡片、SVG 趋势图、运行摘要
│       │   ├── HistoryTab.vue  # 历史：日期筛选、表格、详情展开、日志弹窗
│       │   ├── DetectionTab.vue # 检测监控：健康检查、质量趋势
│       │   ├── TestingTab.vue  # 系统测试：控制、进度、日志、下载链接
│       │   ├── SettingsTab.vue # 配置：文本编辑器、参数表单
│       │   ├── ScannerTab.vue  # 频道扫描：控制、进度、日志
│       │   ├── ScanConfigTab.vue # 扫描配置：API Key 管理、定时设置
│       │   ├── ScanResultsTab.vue # 扫描结果：分页表格、筛选、导出
│       │   ├── IpScanTab.vue   # IP 扫描：输入、配置、结果
│       │   └── LogPanel.vue    # 公共日志面板组件
│       ├── composables/
│       │   ├── useTheme.js     # 深色/浅色主题切换
│       │   ├── usePolling.js   # 轮询定时器（指数退避、Tab 可见性感知）
│       │   ├── useClipboard.js # 剪贴板操作
│       │   └── useDialogDrag.js # 对话框拖拽
│       └── utils/
│           ├── date.js         # 日期工具函数
│           ├── platform.js     # 平台工具函数
│           └── quality.js      # 质量评估工具函数
│
├── dist/                       # 前端构建产物（gitignore，需 npm run build）
├── output/                     # TXT/M3U 输出目录，运行后生成
├── requirements.txt            # Python 依赖
├── basic_auth.json             # Web 后台 BasicAuth 配置
├── Dockerfile                  # Docker 镜像构建文件（多阶段构建）
├── docker-compose.yml          # Docker Compose 编排文件
├── frontend-style-guide.md     # 前端开发规范文档
├── CHANGELOG.md                # 更新日志
└── LICENSE                     # MIT 许可证
```

## Web 标签页说明

前端使用 [TDesign Vue Next](https://tdesign.tencent.com/vue-next/overview) 组件库构建，支持深色/浅色主题切换。

| 标签 | 说明 |
| --- | --- |
| 总览 | 通过率趋势图、统计卡片、运行摘要和值得关注 |
| 历史明细 | 测速历史列表，日期筛选，展开查看详细结果和日志 |
| 系统测试 | 触发/停止测速、实时进度和日志、TXT/M3U 下载和预览 |
| 系统配置 | 编辑订阅源、频道模板、别名映射，调整系统参数 |
| 频道扫描 | 触发/停止扫描、健康检查、实时进度和日志（SSE 推送） |
| 扫描配置 | API Key 管理、扫描参数、定时扫描设置 |
| 检测监控 | 健康检查、质量趋势、频道可用性监控（SSE 推送） |
| 扫描结果 | 查看扫描频道列表、按分类/省份过滤、送入测速、导出 M3U |
| IP 扫描 | 批量 IP/域名扫描、多 IPTV 系统检测、结果查看和送入测速 |

### 快捷键

| 快捷键 | 功能 |
| --- | --- |
| `Ctrl+S` | 保存当前配置 |
| `Ctrl+F` | 打开搜索/过滤 |
| `Alt+1` | 切换到"总览"标签页 |
| `Alt+2` | 切换到"历史明细"标签页 |
| `Alt+3` | 切换到"系统测试"标签页 |
| `Alt+4` | 切换到"系统配置"标签页 |
| `Alt+5` | 切换到"频道扫描"标签页 |
| `Alt+6` | 切换到"扫描配置"标签页 |
| `Alt+7` | 切换到"检测监控"标签页 |
| `Alt+8` | 切换到"扫描结果"标签页 |
| `Alt+9` | 切换到"IP 扫描"标签页 |

快捷键在输入框获得焦点时不会触发，避免干扰正常输入。

## API 响应格式

所有 API 端点返回统一的 JSON 格式：

```json
{
  "ok": true,
  "data": { ... }
}
```

或错误时：

```json
{
  "ok": false,
  "error": "错误信息"
}
```

分页请求的响应格式：

```json
{
  "ok": true,
  "data": {
    "items": [...],
    "total": 100,
    "page": 1,
    "page_size": 20
  }
}
```

注意：分页参数 `page_size` 最大值为 200，超过限制会被自动截断。

## 扫描模块参数

在"频道扫描"标签页的配置区域可设置以下参数：

### API Key 配置

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `quake_api_key` | `""` | Quake 360 API Key（单 Key，向后兼容） |
| `hunter_api_key` | `""` | Hunter 鹰图 API Key（单 Key，向后兼容） |
| `daydaymap_api_key` | `""` | DayDayMap API Key（单 Key，向后兼容） |
| `fofa_api_key` | `""` | Fofa API Key（单 Key，向后兼容） |
| `fofa_email` | `""` | Fofa 邮箱（Fofa 认证必需） |
| `quake_api_keys` | `[]` | Quake 多 Key 列表（支持轮转） |
| `hunter_api_keys` | `[]` | Hunter 多 Key 列表（支持轮转） |
| `daydaymap_api_keys` | `[]` | DayDayMap 多 Key 列表（支持轮转） |
| `fofa_api_keys` | `[]` | Fofa 多 Key 列表（支持轮转） |

### 扫描控制

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `enabled_platforms` | `[]` | 启用的扫描平台列表 |
| `selected_provinces` | `[]` | 扫描省份过滤（多选，空表示全国） |
| `operator` | `""` | 运营商过滤（电信/联通/移动/广电） |
| `quake_size` | `200` | Quake 每次扫描返回的最大条数（1-10000） |
| `hunter_size` | `200` | Hunter 每次扫描返回的最大条数（1-10000） |
| `daydaymap_size` | `200` | DayDayMap 每次扫描返回的最大条数（1-10000） |
| `fofa_size` | `200` | Fofa 每次扫描返回的最大条数（1-10000） |
| `ddgs_enabled` | `false` | 是否启用 DuckDuckGo 扫描 |
| `scan_ports` | `[8080, 80, 443, 9981, 8888, 8000, 9090, 3000, 5000, 8443]` | DDGS 和 ISP 扫描的端口列表 |

### C 段扫描

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `enable_c_scan` | `true` | 是否开启 C 段扩展扫描 |
| `c_scan_limit` | `50` | C 段单段扫描 IP 数上限（1-5000） |
| `c_segment_max_segments` | `8` | C 段最大子网数（1-50） |
| `c_segment_max_total_ips` | `200` | C 段最大总 IP 数（1-5000） |

### 定时扫描

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `daily_full_update` | `true` | 每天扫描（关闭后按 `update_days` 选择星期几） |
| `update_time` | `"03:00"` | 定时扫描时间（HH:MM 格式） |
| `update_days` | `[0,1,2,3,4,5,6]` | 定时扫描的星期几（0=周一, 6=周日） |

### 深度检测

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `deep_concurrent` | `15` | 深度检测并发数（1-200） |
| `deep_batch_size` | `50` | 深度检测批次大小（1-500） |

### 健康检测与复活

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `detection_interval_minutes` | `120` | 健康检测间隔（分钟，0-10080） |
| `detection_cycle_timeout_minutes` | `30` | 检测周期超时（分钟，1-1440） |
| `deletion_threshold` | `3` | 连续失败删除阈值（1-100） |
| `quality_history_keep_days` | `90` | 质量历史保留天数（1-365） |
| `stable_channel_multiplier` | `3` | 稳定频道倍数（1-10） |
| `resurrection_enabled` | `true` | 是否启用频道复活 |
| `resurrection_interval_hours` | `24` | 频道复活间隔（小时，1-720） |

### ISP 情报

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `isp_intelligence_enabled` | `false` | 是否启用 ISP 情报 |
| `hot_segment_min_channels` | `3` | 热门段最少频道数（1-1000） |
| `hot_segment_scan_limit` | `200` | 热门段扫描限制（1-5000） |

### 社区源

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `community_sources_enabled` | `false` | 是否启用社区源 |
| `community_source_urls` | `[]` | 社区源 URL 列表 |
| `github_proxy` | `""` | GitHub 代理地址（国内网络用） |

### 质量评估

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `stability_weights` | `{"bandwidth": 0.35, "stutter": 0.25, "jitter": 0.20, "empty_rate": 0.15, "delay": 0.05}` | 稳定性评分权重配置 |
| `quality_thresholds` | `{"stability_high": 60, "stability_low": 30, "max_delay_ms": 2000, "min_bandwidth_kbps": 300}` | 质量评估阈值配置 |

## 健康检查

系统提供增强的健康检查功能，可通过 `/api/health` 端点访问。

### 检查项目

| 检查项 | 说明 |
| --- | --- |
| FFmpeg | 检查 FFmpeg 是否可用及版本信息 |
| 磁盘空间 | 检查数据目录和输出目录的可用空间 |
| 内存使用 | 检查系统内存使用率 |
| 扫描模块 | 检查扫描模块的运行状态 |
| 数据库 | 检查数据库连接和完整性 |
| 运行时间 | 系统启动时间和运行时长 |
| 版本信息 | 当前系统版本号 |

### 响应格式

健康检查 API 返回统一的 JSON 格式：

```json
{
  "ok": true,
  "data": {
    "status": "healthy",
    "version": "1.6.2",
    "uptime": "2h 30m",
    "checks": {
      "ffmpeg": {"status": "ok", "version": "6.0"},
      "disk": {"status": "ok", "free_gb": 120.5},
      "memory": {"status": "ok", "usage_percent": 45.2},
      "scanner": {"status": "ok", "active_tasks": 0},
      "database": {"status": "ok", "type": "MySQL"}
    }
  }
}
```

### 搜索查询说明

四平台的默认搜索查询定义在 `scanner_integration/config_bridge.py` 中，使用 OR 组合覆盖常见 IPTV 特征：

| 平台 | 默认查询语法 | 说明 |
| --- | --- | --- |
| Quake 360 | `body="..."` | 使用 `body` 搜索页面内容 |
| Hunter 鹰图 | `web.body="..."` | 使用 `web.body` 搜索网页正文 |
| DayDayMap | `body="..."` | 使用 `body` 搜索页面内容 |
| Fofa | `body="..."` | 使用 `body` 搜索页面内容 |

默认查询特征覆盖：

| 特征字符串 | 说明 |
| --- | --- |
| `/iptv/live/zh_cn.js` | 常见 IPTV 系统 JS 文件路径 |
| `1000.json?key=txiptv` | IPTV JSON 接口特征 |
| `ZHGXTV` | ZHGX IPTV 系统特征 |
| `jsmpeg-streamer` | JSMpeg 流媒体系统特征 |
| `IPTV互动电视系统` | IPTV 互动电视系统标题特征 |
| `/iptv/live/` | IPTV 直播路径通用特征 |
| `IPTV管理系统` | IPTV 管理系统标题特征 |
| `酒店IPTV` | 酒店 IPTV 系统标题特征 |
| `getChannelList` | 频道列表 API 接口特征 |
| `EasyLive` | EasyLive IPTV 系统特征 |
| `Hybroad` | Hybroad IPTV 系统特征 |
| `udpxy` | udpxy 代理服务特征 |
| `tvheadend` | Tvheadend 流媒体系统特征 |
| `Xtream` + `IPTV` | Xtream IPTV 系统组合特征 |

省份和运营商过滤条件会自动追加到默认查询之后（使用 `AND` / `&&` 连接）。

## 别名系统

测速模块和扫描模块共享同一套别名系统（`engine/alias.py`）。别名数据存储在 MySQL `config_data` 表（key=`alias`）中。

别名格式：每行一个主名映射，第一列是主名，后续列是别名。以 `re:` 开头的别名会按正则表达式匹配。匹配引擎使用字典 O(1) 精确查找 + 预编译正则兜底，支持 4 万+ 条别名高效匹配。

### 别名功能特性

- **缓存机制**：首次调用 `load_aliases()` 后缓存，避免重复解析。
- **ReDoS 防护**：正则表达式模式长度限制 200 字符，防止正则表达式拒绝服务攻击。
- **画质后缀去除**：自动去除频道名末尾的画质后缀（高清/HD/4K 等）。
- **CCTV 归一化**：支持中文数字（中央一套）、IPTV5+ 等变体归一化。
- **黑名单过滤**：自动过滤无效频道名（如纯数字、过短名称等）。
- **自动分类**：根据频道名自动分类为央视频道、卫视频道、各省频道等。

## 常见问题

**Q: 修改配置后没有生效？**
请确认是在 Web 后台保存到数据库。旧的 `subscribe.txt`、`alias.txt`、`demo.txt` 不再被读取。每轮测速开始时会重新读取数据库配置。

**Q: FFmpeg 未找到？**
安装 FFmpeg 并确保命令行可直接执行 `ffmpeg`。如果不在 `PATH` 中，设置 `FFMPEG_BIN` 指向可执行文件。

**Q: 所有频道都不通过？**
在 Web 后台降低 `min_bandwidth_MBps`、`min_width`、`min_height`，或检查频道模板和别名是否能匹配订阅源里的实际频道名。

**Q: 并发太高导致机器或网络压力大？**
降低 `max_workers`，必要时设置 `system_bandwidth_limit_MBps`。

**Q: 想清空历史或配置？**
历史数据在 MySQL 数据库中。清空数据库会同时清空配置、历史、日志和进度；操作前请先备份。

**Q: 扫描模块报错 aiohttp 未安装？**
运行 `pip install aiohttp>=3.9.0` 安装扫描模块依赖。扫描模块为可选功能，不安装 aiohttp 不影响测速模块的正常使用。

如果启用了 DDGS 扫描，还需要额外安装 `ddgs`：`pip install ddgs`。

**Q: 扫描需要 API Key 吗？**
是的。至少需要配置一个搜索引擎的 API Key（Quake 360、Hunter 鹰图、DayDayMap 或 Fofa 之一）。在"频道扫描"标签页的配置区域填写，点击旁边的"获取 ↗"链接可跳转到对应平台申请。

**Q: 如何设置定时扫描？**
在"频道扫描"标签页的配置区域底部，勾选要扫描的星期几（或勾选"每天"），设置扫描时间，保存配置即可。页面会显示下次扫描的倒计时。定时扫描在后台自动执行，无需手动触发。

**Q: 首次部署或更新后页面空白/报错？**
需要先构建前端：`cd frontend && npm install && npm run build`。构建完成后 `dist/` 目录会生成 SPA 文件，Flask 启动时自动服务。

**Q: 前端开发调试？**
运行 `python -m web --dev`，会自动启动 Vite 开发服务器（`:3000`）+ Flask API 服务器（`:58080`）。修改 Vue 源码后浏览器自动热更新，无需手动构建。

**Q: 如何启用社区源？**
在扫描配置中设置 `community_sources_enabled` 为 `true`，并可选配置 `community_source_urls` 和 `github_proxy`（国内网络用）。默认会从 GitHub 上的公开 IPTV M3U 仓库采集频道。

**Q: 如何启用 ISP 情报？**
在扫描配置中设置 `isp_intelligence_enabled` 为 `true`。系统会分析历史扫描数据，发现 IPTV 密集的 IP 段进行主动扫描。

**Q: 如何启用频道复活？**
在扫描配置中设置 `resurrection_enabled` 为 `true`，并配置 `resurrection_interval_hours`（默认 24 小时）。系统会定期尝试复活已删除的频道。

**Q: 如何配置 Webhook 通知？**
在系统配置中设置 `webhook_enabled` 为 `true`，并配置 `webhook_url`。支持 Telegram、企业微信等 Webhook 服务。可分别配置测速、扫描、检测事件的通知开关。

**Q: 数据库连接失败？**
检查 `database/db_config.json` 配置是否正确，确保 MySQL 服务已启动且可访问。配置示例见 `database/db_config.json.example`。

**Q: 如何备份数据库？**
使用 MySQL 自带的备份工具（如 `mysqldump`）定期备份。建议在低峰期进行备份。

## 更新日志

详细的版本更新记录请查看 [CHANGELOG.md](CHANGELOG.md)。

**重要：每次代码修改都必须将更新内容写入 [CHANGELOG.md](CHANGELOG.md) 文件。** 请遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 格式规范。

## 许可证

本项目采用 [MIT 许可证](LICENSE) 开源。

## 致谢

- [TDesign Vue Next](https://tdesign.tencent.com/vue-next/overview) - 前端组件库
- [Flask](https://flask.palletsprojects.com/) - Web 后台框架
- [MySQL](https://www.mysql.com/) / [PyMySQL](https://pymysql.readthedocs.io/) - 数据库引擎
- [FFmpeg](https://ffmpeg.org/) - 音视频处理工具
- [aiohttp](https://docs.aiohttp.org/) - 异步 HTTP 客户端

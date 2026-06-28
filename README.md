# iptv-all-in-one

从多个 M3U 订阅源中筛选可用且质量较高的 IPTV 频道，支持 FFmpeg 分辨率检测、带宽测速、频道别名归一、模板化输出、Web 后台配置、历史记录和定时运行。

集成 IPTV 频道扫描模块，可通过搜索引擎 API（Quake/Hunter/DayDayMap/Fofa）自动发现酒店 IPTV 服务器，提取频道列表并送入测速流水线。

## 当前版本说明（v1.6.16）

本项目当前以 MySQL 作为主要数据存储。Docker/Compose 部署优先通过 `.env` 中的 `DB_*` 环境变量连接数据库；直接运行源码时也可以使用 `DB_*` 环境变量，未设置 `DB_HOST` 时才读取 `database/db_config.json`。

旧版 README 中提到的 `config.json`、`subscribe.txt`、`alias.txt`、`demo.txt` 已不再作为日常配置入口。现在请通过 Web 后台的"系统配置"页面维护：

| 数据 | 当前存储位置 | 说明 |
| --- | --- | --- |
| 系统参数 | MySQL `config_data` 表，key 为 `config` | 测速时长、并发数、分辨率阈值、运行模式等 |
| 订阅源 | `config_data` 表，key 为 `subscribe` | 每行一个 M3U 地址 |
| 频道模板 | `config_data` 表，key 为 `demo` | 决定要匹配、测速和输出哪些频道 |
| 别名映射 | `config_data` 表，key 为 `alias` | 将不同频道名归一到模板中的主名 |
| 扫描配置 | `config_data` 表，key 为 `scan_config` | 扫描模块的 API Key、平台、省份等配置 |
| 频道方案 | `config_data` 表，key 为 `profiles` / `profile:<name>` | 可供订阅接口按方案输出的扩展频道模板 |
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

### 最近更新摘要

- README 已按当前代码重新校准：区分 Docker `.env` 与源码运行 `database/db_config.json` 的数据库配置入口。
- 健康检查说明改为当前真实响应：默认轻量返回，设置 `IPTV_HEALTH_DETAILED=1` 后才返回版本、运行时间、磁盘、内存、调度和最近测速摘要。
- 修正 Gunicorn 端口、API 响应格式例外、结果订阅端点和 Webhook 可用性说明，避免把未开放的后台配置写成可直接使用。

完整记录请查看 [CHANGELOG.md](CHANGELOG.md)。GitHub 仓库首页默认只渲染 README，所以上面保留最近更新摘要，完整变更仍以 CHANGELOG 为准。

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
- 质量评分系统：基于带宽和延迟计算频道质量分数，用于排序和筛选。

### 扫描模块

- 通过搜索引擎 API（Quake 360、Hunter 鹰图、DayDayMap、Fofa）自动发现酒店 IPTV 服务器。
- 默认搜索优先保留 TXIPTV、直播 JSON 和 ZHGX 等高价值入口，避免泛品牌词、JSMpeg 和频道 API 过度消耗积分。
- 质量优先查询：在基础查询之外，按 TXIPTV、标准直播接口、ZHGXTV、Tvheadend 等画像追加搜索，优先补充最近测速表现更好的候选源。
- 质量热点补源：基于历史频道的稳定性、延迟、带宽和质量状态识别高价值 /24 网段，围绕稳定源继续探测。
- 支持 ZHGXTV、JSMpeg、Tvheadend、IPTV互动、EasyLive、Hybroad、udpxy、Xtream 等多种 IPTV 系统的独立扫描和频道提取。
- C 段扫描：对已发现的 IP 所在 /24 子网进行扩展扫描，支持智能采样和限制。
- 快速过滤（HEAD 请求验证）+ 深度检测（带宽/延迟/稳定性/分辨率）。
- 轻量级 H.264 分辨率解析：无需调用 ffprobe，直接解析 TS 流获取分辨率。
- 自动频道名归一和分类（央视频道、卫视频道、各省频道）。
- 省份/城市/运营商过滤。
- 扫描结果可选择性送入测速流水线，经 FFmpeg 深度检测后输出。
- 定期检测模块：自动检测已发现频道的可用性，连续失败达到阈值自动移除。
- 频道复活机制：定期尝试复活已删除的频道，避免误删。
- ISP 情报分析：分析历史扫描数据，发现 IPTV 密集的 IP 段进行主动扫描。
- 社区源聚合：从 GitHub 上的公开 IPTV M3U 仓库采集频道列表。
- 域名扫描：支持 DNS/Censys/RapidDNS/crt.sh 域名扫描发现 IPTV 服务。
- API Key 多 Key 轮转：支持 Quake/Hunter/DayDayMap/Fofa 多 Key 轮转，避免单 Key 限流。
- 稳定性评分：基于带宽、卡顿、抖动、空包率、延迟等多维度计算频道稳定性。
- 平台级采集日志：展示 API 命中、实际探测、频道提取和 C 段补充数量，便于判断是 API 返回少还是提取过滤少。
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
- 健康检查：默认轻量检查数据库、FFmpeg 和扫描模块；设置 `IPTV_HEALTH_DETAILED=1` 后返回版本、运行时间、磁盘、内存、调度和最近测速摘要。
- Vite 开发模式，支持前端热更新。
- 键盘快捷键支持：Ctrl+S 保存、Ctrl+F 搜索、Alt+1-9 切换标签页。
- 无障碍访问 (a11y) 支持：语义化标签、ARIA 属性、焦点管理。
- 操作确认弹窗：终止测试、停止扫描、强制清除、清空日志等危险操作需确认。
- 表单即时验证反馈。
- 多数管理类 API 使用统一响应格式：`{'ok': True/False, 'data': ...}`；健康检查、下载、订阅和 SSE 端点按用途返回专用格式。
- 全局错误处理器：404/500/405 返回 JSON 而非 HTML。
- 分页参数上限校验（最大 200 条）。
- 前端轮询优化：指数退避和 Tab 可见性感知。

### 数据库层

- MySQL 数据库存储；Docker/Compose 使用 `.env` 中的 `DB_*` 环境变量，源码直跑未设置 `DB_HOST` 时读取 `database/db_config.json`。
- 数据库自动迁移：首次启动自动迁移旧版 config.json 和 history.json。
- 日志批量写入：减少 commit 次数，提高性能。
- 日志保留策略：测速日志 30 天、扫描日志 7 天、持久化结果 90 天、质量历史 90 天。
- 数据库最多保留最近 50 轮历史记录。
- 复合索引和唯一约束优化查询性能。
- 线程安全的写入锁保护并发写入。

## 快速开始

### Docker 部署（推荐）

Docker 部署默认使用 Docker Compose 编排两个独立容器：

- `iptv-all-in-one`：运行 Web 后台、测速程序和 FFmpeg。
- `mysql`：运行 MySQL 8.4 LTS，默认带轻量内存参数，数据保存在 Docker volume `mysql_data` 中。

也就是说，MySQL 不是打包进 `iptv-all-in-one` 应用容器里，而是由 Compose 自动拉起一个独立的 MySQL 容器。两个容器在同一个 Docker 内部网络里通信，应用默认通过 `DB_HOST=mysql` 连接数据库。

> 下面命令使用新版 Docker 写法 `docker compose`。如果你的环境只支持旧版 Compose，可以把命令替换成 `docker-compose`。
>
> 注意：单独执行 `docker pull juzhic/iptv-all-in-one:latest` 只会下载应用镜像，不会启动应用，也不会启动 MySQL。要自动启动应用和默认 MySQL 容器，请使用下面的 `docker compose up -d`。

**方式 A：使用默认 MySQL 容器**

```bash
# 创建环境变量文件，并自动生成随机 DB_PASSWORD
python generate_env.py

# 如果你的系统没有 python 命令，改用：
# python3 generate_env.py

# 启动服务
docker compose up -d

# 访问
http://localhost:58080
```

首次启动前必须设置 `.env` 里的 `DB_PASSWORD`，它会作为默认 MySQL 容器的 root 密码。推荐运行 `python generate_env.py` 自动生成随机密码；如果手动复制 `.env.example`，也请填写强密码后再启动。默认数据库镜像固定为 `mysql:8.4`，MySQL 数据会自动保存在 Docker volume 中，重启或更新应用容器不会丢失。

已有部署如果已经初始化过 `mysql_data`，请保持 `.env` 中的 `DB_PASSWORD` 与当前 MySQL root 密码一致。MySQL 官方镜像只在首次初始化数据目录时读取 `MYSQL_ROOT_PASSWORD`，后续直接改 `.env` 不会自动修改数据库里的 root 密码；需要先进入 MySQL 修改密码，再同步更新 `.env`。

默认 MySQL 端口只映射到宿主机本地 `127.0.0.1:3306`，方便在服务器本机使用数据库客户端连接，不会对局域网或公网开放。如果宿主机 3306 已被占用，可在 `.env` 中修改 `MYSQL_HOST_PORT`。

默认 `docker-compose.yml` 已为 8G 或更小服务器收紧 MySQL 基础内存占用：关闭 Performance Schema，并降低 InnoDB 缓冲池、日志缓冲、连接数和表缓存。需要更高并发或更大数据量时，可在 `.env` 中调大 `MYSQL_INNODB_BUFFER_POOL_SIZE`、`MYSQL_MAX_CONNECTIONS` 等参数后重启。

**MySQL 数据持久化与备份**

默认 Compose 已将 MySQL 数据目录挂载到 Docker volume：

```yaml
services:
  mysql:
    volumes:
      - mysql_data:/var/lib/mysql

volumes:
  mysql_data:
```

因此执行 `docker compose pull && docker compose up -d` 更新应用，或重启 `iptv-all-in-one` 应用容器时，MySQL 数据仍会保留在 `mysql_data` 中。停止服务时建议使用 `docker compose down`；不要使用 `docker compose down -v`，后者会删除 `mysql_data` 并清空数据库。

建议定期备份数据库，默认 MySQL 容器模式可执行：

```bash
docker compose exec mysql sh -c 'mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --databases "$MYSQL_DATABASE"' > iptv-all-in-one.sql
```

恢复到默认 MySQL 容器时可执行：

```bash
docker compose exec -T mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD"' < iptv-all-in-one.sql
```

**方式 B：使用已有的外部 MySQL**

编辑 `.env` 文件：

```bash
DB_HOST=你的MySQL地址
DB_PORT=3306
DB_USER=你的MySQL用户
DB_PASSWORD=你的MySQL密码
DB_NAME=iptv-all-in-one
DB_CHARSET=utf8mb4
```

然后使用外部 MySQL 专用 compose 文件启动，这样不会额外创建 `mysql` 容器：

```bash
docker compose -f docker-compose.external-mysql.yml up -d
```

使用这个模式后，后续查看日志、更新和停止服务也请继续带上同一个 `-f docker-compose.external-mysql.yml` 参数。

如果 MySQL 就装在运行 Docker 的这台宿主机上：

- Docker Desktop（Windows/macOS）通常把 `DB_HOST` 写成 `host.docker.internal`。
- Linux 服务器通常写宿主机局域网 IP，或确保 MySQL 监听地址允许 Docker 容器访问。

外部 MySQL 需要提前创建数据库并授权，表结构会由程序启动时自动初始化：

```sql
CREATE DATABASE `iptv-all-in-one` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'iptv'@'%' IDENTIFIED BY '请换成强密码';
GRANT ALL PRIVILEGES ON `iptv-all-in-one`.* TO 'iptv'@'%';
FLUSH PRIVILEGES;
```

**更新镜像**：

```bash
# 默认 MySQL 容器模式
docker compose pull
docker compose up -d

# 外部 MySQL 模式
docker compose -f docker-compose.external-mysql.yml pull
docker compose -f docker-compose.external-mysql.yml up -d
```

查看运行状态和日志：

```bash
docker compose ps
docker compose logs -f iptv-all-in-one

# 外部 MySQL 模式
docker compose -f docker-compose.external-mysql.yml ps
docker compose -f docker-compose.external-mysql.yml logs -f iptv-all-in-one
```

#### 飞牛 fnOS 图形界面部署

飞牛上不要只执行 `docker pull`。`docker pull` 只会下载镜像，不会创建应用容器，也不会启动 MySQL。推荐在飞牛 Docker 管理器里使用 Compose 项目部署。

1. 在飞牛桌面打开 **Docker**。如果还没有 Docker，先到应用中心安装 Docker，并按提示选择 Docker 数据存储位置。
2. 打开 **Docker** 后，进入左侧 **Compose**，点击 **新增项目**。
3. 项目名称填写 `iptv-all-in-one`。
4. 项目路径选择一个专门目录，例如 `/vol1/1000/docker/iptv-all-in-one`。路径以你的飞牛实际存储空间为准。
5. 创建或编辑 `docker-compose.yml`，粘贴下面内容。
6. 保存后点击启动。启动完成后访问 `http://飞牛IP:58080`。

默认模式会启动两个容器：`iptv-all-in-one` 应用容器和 `mysql` MySQL 容器。

```yaml
services:
  mysql:
    image: mysql:8.4
    container_name: mysql
    command:
      - --performance-schema=OFF
      - --innodb-buffer-pool-size=64M
      - --innodb-log-buffer-size=8M
      - --max-connections=50
      - --table-open-cache=200
      - --table-definition-cache=400
    ports:
      - "127.0.0.1:3306:3306"
    volumes:
      - mysql_data:/var/lib/mysql
    environment:
      MYSQL_ROOT_PASSWORD: 请换成强随机密码
      MYSQL_DATABASE: iptv-all-in-one
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost"]
      interval: 10s
      timeout: 5s
      retries: 3

  iptv-all-in-one:
    image: juzhic/iptv-all-in-one:latest
    container_name: iptv-all-in-one
    ports:
      - "58080:58080"
    depends_on:
      mysql:
        condition: service_healthy
    environment:
      - DB_HOST=mysql
      - DB_PORT=3306
      - DB_USER=root
      - DB_PASSWORD=请换成同一个强随机密码
      - DB_NAME=iptv-all-in-one
      - DB_CHARSET=utf8mb4
      - TZ=Asia/Shanghai
    restart: unless-stopped

volumes:
  mysql_data:
```

建议首次部署前把上面两处密码改成同一个强随机密码，并保持 `MYSQL_ROOT_PASSWORD` 和 `DB_PASSWORD` 一致。上面的 MySQL `command` 是低内存默认参数；如果机器内存充足或并发较高，可以按需调大 `innodb-buffer-pool-size` 和 `max-connections`。`ports` 只绑定 `127.0.0.1`，因此只有宿主机本地能连接 MySQL。

如需改访问端口，例如想用 `8080` 访问，只改端口映射左边：

```yaml
ports:
  - "8080:58080"
```

然后访问 `http://飞牛IP:8080`。

如果你已经有独立 MySQL，不想启动 `mysql` 容器，请在 Compose 项目里改用 `docker-compose.external-mysql.yml` 的内容，并填写你的 `DB_HOST`、`DB_USER`、`DB_PASSWORD` 和 `DB_NAME`。

---

### 手动安装

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
    "database": "iptv-all-in-one",
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
  "realm": "iptv-all-in-one"
}
```

如果文件缺失且未设置 `IPTV_AUTH_PASSWORD`，启动时会生成一个随机密码并打印在日志里。建议创建 `basic_auth.json` 或设置 `IPTV_AUTH_USERNAME` / `IPTV_AUTH_PASSWORD`，让登录凭据可持久化。

结果订阅下载和健康检查保持公开：`/api/download/txt`、`/api/download/m3u`、`/api/subscribe.m3u` 和 `/api/health`。

开发模式下，Vite 代理会优先读取 `IPTV_AUTH_USERNAME` / `IPTV_AUTH_PASSWORD`，否则读取同一份 `basic_auth.json` 并转发 BasicAuth 头，因此 `http://localhost:3000` 下的总览、历史、扫描等 API 页面可直接调试。

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
gunicorn -w 1 -b 0.0.0.0:58080 --timeout 120 web:app
```

参数说明：
- `-w 1`：单工作进程。后台测速、SSE 和停止信号依赖进程内状态，生产环境建议保持单 worker。
- `-b 0.0.0.0:58080`：监听所有网卡的 58080 端口。Gunicorn 不读取 `IPTV_PORT`，如需改端口请直接修改 `-b` 参数。
- `--timeout 120`：请求超时 120 秒（测速任务耗时较长）

自定义 Gunicorn 端口示例：

```bash
gunicorn -w 1 -b 0.0.0.0:8080 --timeout 120 web:app
```

3. 使用 Systemd 打包为服务（可选）：

创建 `/etc/systemd/system/iptv-all-in-one.service`：

```ini
[Unit]
Description=iptv-all-in-one Service
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/path/to/iptv-all-in-one
ExecStart=/path/to/venv/bin/gunicorn -w 1 -b 127.0.0.1:58080 --timeout 120 web:app
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
sudo systemctl enable iptv-all-in-one
sudo systemctl start iptv-all-in-one
```

### 方式三：Nginx 反向代理

在 `/etc/nginx/conf.d/iptv-all-in-one.conf` 中添加：

```nginx
server {
    listen 80;
    server_name your-domain.com;

    # 基本认证（可选，推荐配合 basic_auth.json 使用）
    # auth_basic "iptv-all-in-one";
    # auth_basic_user_file /etc/nginx/.htpasswd;

    location / {
        proxy_pass http://127.0.0.1:58080;  # 如果修改了服务端口或 Docker 映射端口，这里也要对应修改
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

项目已包含 `Dockerfile`、`docker-compose.yml` 和 `docker-compose.external-mysql.yml`。生产环境推荐优先使用 Compose，数据库、应用、端口和重启策略都更清晰。

**默认模式：应用容器 + MySQL 容器**

```bash
# 创建环境变量文件，并自动生成随机 DB_PASSWORD
python generate_env.py

# 如果你的系统没有 python 命令，改用：
# python3 generate_env.py

docker compose up -d
```

这会启动：

- `iptv-all-in-one`：应用容器，容器内固定监听 `58080`。
- `mysql`：MySQL 8.4 LTS 容器，默认带轻量内存参数，数据写入 `mysql_data` volume。

默认 `docker-compose.yml` 会关闭 MySQL Performance Schema，并把 InnoDB 缓冲池、日志缓冲、最大连接数和表缓存调到更适合小服务器的值。若后续数据量或并发明显增加，可在 `.env` 中调大对应的 `MYSQL_*` 参数后执行 `docker compose up -d` 重新创建 MySQL 容器。

默认 MySQL 仅映射到宿主机本地地址 `127.0.0.1:${MYSQL_HOST_PORT:-3306}`，不会开放给局域网或公网。需要在宿主机上用数据库客户端连接时，主机填 `127.0.0.1`，端口默认 `3306`。

**外部 MySQL 模式：只启动应用容器**

```bash
python generate_env.py

# 编辑 .env，把 DB_HOST/DB_USER/DB_PASSWORD/DB_NAME 改成外部 MySQL
docker compose -f docker-compose.external-mysql.yml up -d
```

使用这个模式后，后续 `pull`、`up`、`logs`、`ps`、`down` 等命令也请继续带上 `-f docker-compose.external-mysql.yml`。

如果只是把 `.env` 的 `DB_HOST` 改成外部地址后继续运行默认 `docker-compose.yml`，应用会连接外部 MySQL，但 Compose 仍会启动 `mysql` 这个本地数据库容器。若不想启动本地 MySQL，请使用 `docker-compose.external-mysql.yml`。

**自定义访问端口**

Compose 中的 `PORT` 是宿主机访问端口，容器内端口固定为 `58080`：

```bash
# .env 文件
PORT=8080

# 或直接指定
PORT=8080 docker compose up -d
```

之后通过 `http://localhost:8080` 访问。

**手动 docker run**

单独运行应用镜像时不会自动启动 MySQL，你必须提供一个可访问的外部 MySQL：

```bash
docker run -d \
  --name iptv-all-in-one \
  -p 58080:58080 \
  -e DB_HOST=你的MySQL地址 \
  -e DB_PORT=3306 \
  -e DB_USER=你的MySQL用户 \
  -e DB_PASSWORD=你的MySQL密码 \
  -e DB_NAME=iptv-all-in-one \
  -e DB_CHARSET=utf8mb4 \
  -e IPTV_AUTH_USERNAME=myuser \
  -e IPTV_AUTH_PASSWORD=mypassword \
  juzhic/iptv-all-in-one:latest
```

如需把宿主机 `8080` 映射到容器内服务，写成 `-p 8080:58080`。

### 环境变量

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `DB_HOST` | MySQL 地址；默认 Compose 内置 MySQL 时为 `mysql` | 未设置 |
| `DB_PORT` | MySQL 端口 | `3306` |
| `DB_USER` | MySQL 用户 | `root` |
| `DB_PASSWORD` | MySQL 密码；默认部署必须设置，推荐用 `python generate_env.py` 随机生成 | 未设置 |
| `DB_NAME` | MySQL 数据库名 | `iptv-all-in-one` |
| `DB_CHARSET` | MySQL 字符集 | `utf8mb4` |
| `MYSQL_HOST_PORT` | 默认 MySQL 容器映射到宿主机本地的端口，仅监听 `127.0.0.1` | `3306` |
| `MYSQL_PERFORMANCE_SCHEMA` | 默认 MySQL 容器是否启用 Performance Schema | `OFF` |
| `MYSQL_INNODB_BUFFER_POOL_SIZE` | 默认 MySQL 容器 InnoDB 缓冲池大小 | `64M` |
| `MYSQL_INNODB_LOG_BUFFER_SIZE` | 默认 MySQL 容器 InnoDB 日志缓冲大小 | `8M` |
| `MYSQL_MAX_CONNECTIONS` | 默认 MySQL 容器最大连接数 | `50` |
| `MYSQL_TABLE_OPEN_CACHE` | 默认 MySQL 容器表打开缓存 | `200` |
| `MYSQL_TABLE_DEFINITION_CACHE` | 默认 MySQL 容器表定义缓存 | `400` |
| `FFMPEG_BIN` | FFmpeg 可执行文件路径 | `ffmpeg`（从 PATH 查找） |
| `IPTV_HOST` | Web 服务监听地址 | `0.0.0.0` |
| `IPTV_PORT` | `python -m web` 直接运行时的 Web 服务端口；官方 Docker 镜像内固定监听 `58080` | `58080` |
| `PORT` | Docker Compose 暴露到宿主机的访问端口 | `58080` |
| `IPTV_AUTH_USERNAME` | BasicAuth 用户名（覆盖配置文件） | `admin` |
| `IPTV_AUTH_PASSWORD` | BasicAuth 密码（覆盖配置文件） | 缺省时随机生成 |
| `IPTV_AUTH_REALM` | BasicAuth 领域名称（覆盖配置文件） | `iptv-all-in-one` |
| `IPTV_HEALTH_DETAILED` | `/api/health` 是否返回磁盘、内存、调度等详细信息；设为 `1` 开启 | 未设置 |
| `PYTHONUNBUFFERED` | 禁用 Python 输出缓冲 | 未设置 |
| `MAX_FFMPEG_WORKERS` | FFmpeg 最大并发数（覆盖配置文件） | 未设置 |
| `CENSYS_API_ID` | Censys API ID（域名扫描用） | 未设置 |
| `CENSYS_API_SECRET` | Censys API Secret（域名扫描用） | 未设置 |

### 安全建议

1. **固定登录凭据**：首次启动且未配置密码时会生成随机密码并打印到日志。生产环境建议创建 `basic_auth.json`，或设置 `IPTV_AUTH_USERNAME` / `IPTV_AUTH_PASSWORD`。
2. **限制访问**：通过防火墙或 Nginx 限制来源 IP
3. **HTTPS**：生产环境务必使用 HTTPS（可通过 Nginx + Let's Encrypt 配置）
4. **数据库备份**：定期备份 MySQL 数据库
5. **凭证管理**：`basic_auth.json` 和 `database/db_config.json` 包含敏感信息，生产环境建议：
   - 通过环境变量传递 BasicAuth 凭证：`IPTV_AUTH_USERNAME`、`IPTV_AUTH_PASSWORD`、`IPTV_AUTH_REALM`
   - `basic_auth.json` 和 `database/db_config.json` 已加入 `.gitignore`，避免意外提交
   - 使用 Docker volumes 挂载而非复制到镜像中

### 目录结构要求

直接运行源码时需确保以下目录可写：

```text
database/           # 直接运行源码且未使用 DB_* 环境变量时，db_config.json 必须存在且可读
output/             # 测速结果输出（运行时自动创建）
dist/               # 前端构建产物（需提前 npm run build）
```

Docker 官方镜像已包含前端构建产物；数据库推荐通过 `.env` 中的 `DB_*` 环境变量配置。

### 常见部署问题

**Q: 启动后页面 404？**
确保已构建前端：`cd frontend && npm run build`，`dist/` 目录存在且包含 `index.html`。

**Q: 端口被占用？**
使用 `lsof -i :58080`（Linux）或 `netstat -ano | findstr :58080`（Windows）查看占用进程并结束。直接运行源码时可通过 `IPTV_PORT` 修改服务端口；Docker Compose 部署时修改 `.env` 里的 `PORT`，例如 `PORT=8080`。

**Q: Gunicorn 启动失败？**
检查 Python 路径是否正确，确保虚拟环境已激活。可先用 `python -m web` 测试基础功能。

**Q: 数据库连接失败？**
Docker 部署优先检查 `.env` 中的 `DB_HOST`、`DB_PORT`、`DB_USER`、`DB_PASSWORD`、`DB_NAME` 是否正确，并用 `docker compose logs -f iptv-all-in-one` 查看连接错误。直接运行源码且未设置 `DB_HOST` 时，检查 `database/db_config.json` 配置是否正确。

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

代码中保留了 `engine/notifications.py` 通知发送工具，但当前默认系统配置、配置保存 API 和前端参数页没有开放 Webhook 字段，因此本版本不把 Webhook 列为可直接在后台启用的功能。

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
/api/subscribe.m3u
```

`/api/subscribe.m3u` 供播放器直接订阅，支持 `format=txt`、`category`、`province`、`codec=h265|h264`、`min_bandwidth`、`profile` 等查询参数。

测速历史、详情、日志和实时进度保存在 MySQL 数据库中，不再依赖 `output/history.json`。当前数据库最多保留最近 50 轮历史记录。日志保留策略：测速日志 30 天、扫描日志 7 天、持久化结果 90 天、质量历史 90 天。

### 输出格式

**TXT 格式**（`output/result.txt`）：
```text
🕘️更新时间,#genre#
2026-06-28 12:00:00,邮箱联系

央视频道,#genre#
CCTV-1,http://example.com/stream1.m3u8
CCTV-2,http://example.com/stream2.m3u8

卫视频道,#genre#
广东卫视,http://example.com/stream3.m3u8
```

**M3U 格式**（`output/result.m3u`）：
```m3u
#EXTM3U x-tvg-url="http://epg.example.com"
#EXTINF:-1 tvg-id="更新时间" tvg-name="更新时间" group-title="🕘️更新时间",2026-06-28 12:00:00
http://localhost/update_time
#EXTINF:-1 tvg-id="CCTV-1" tvg-name="CCTV-1" tvg-logo="https://www.xn--rgv465a.top/tvlogo/CCTV-1.png" group-title="央视频道",CCTV-1
http://example.com/stream1.m3u8
#EXTINF:-1 tvg-id="CCTV-2" tvg-name="CCTV-2" tvg-logo="https://www.xn--rgv465a.top/tvlogo/CCTV-2.png" group-title="央视频道",CCTV-2
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
iptv-all-in-one/
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
│   │   ├── params.py           # 路由参数边界校验工具
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
│   ├── db_config.json          # 源码直跑且未设置 DB_HOST 时使用的 MySQL 连接配置（gitignore）
│   └── db_config.json.example  # 数据库配置示例
│
├── engine/                     # 测速引擎核心
│   ├── __init__.py             # 统一导出引擎接口
│   ├── test_engine.py          # 核心测速引擎：频道匹配、M3U 源解析、测速编排、输出生成
│   ├── ffmpeg_test.py          # FFmpeg 分析、带宽采样和 HTTP 拉流检测
│   ├── alias.py                # 共享别名模块（测速和扫描共用）
│   ├── discovery.py            # 频道发现：从扫描结果中提取和过滤频道
│   ├── notifications.py        # 通知发送工具（支持 SSRF 防护，当前未接入默认后台配置）
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
│       │   ├── OverviewTab.vue # 总览：统计卡片、ECharts 趋势图、运行摘要
│       │   ├── HistoryTab.vue  # 历史：日期筛选、表格、详情展开、日志弹窗
│       │   ├── DetectionTab.vue # 检测监控：检测轮次、运行日志、明细和重检
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
├── docker-compose.yml          # Docker Compose 编排文件（默认应用 + MySQL 容器）
├── docker-compose.external-mysql.yml # 外部 MySQL 部署，仅启动应用容器
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
| 检测监控 | 定期检测配置、检测轮次、运行日志、频道检测明细和手动重检（SSE 推送） |
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

多数管理类 API 返回统一的 JSON 格式：

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

例外：`/api/initial` 返回前端首屏数据对象；`/api/health` 返回监控友好的轻量健康检查对象；`/api/download/*`、`/api/subscribe.m3u`、`/api/ip-scan/export` 返回文件内容；`/api/*/stream` 为 SSE 事件流。

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
| `cost_saver_mode` | `true` | 省积分模式：仅在未手动指定平台时优先使用 Quake，并跳过低收益隐藏补扫；关闭后会按已配置 Key 自动启用所有可用 API 平台 |
| `ddgs_enabled` | `false` | 是否启用 DuckDuckGo 扫描 |
| `scan_ports` | `[8080, 80, 443, 9981, 8888, 8000, 9090, 3000, 5000, 8443]` | DDGS 和 ISP 扫描的端口列表 |

### C 段扫描

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `enable_c_scan` | `true` | 是否开启 C 段扩展扫描 |
| `c_scan_limit` | `50` | C 段单段扫描 IP 数上限（1-5000） |
| `c_segment_max_segments` | `8` | C 段最大子网数（1-50） |
| `c_segment_max_total_ips` | `200` | C 段最大总 IP 数（1-5000） |

### 质量优先发现

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `quality_discovery_enabled` | `true` | 是否启用质量优先查询，额外执行 TXIPTV、直播接口、ZHGXTV、Tvheadend 等画像查询 |
| `quality_discovery_platforms` | `[]` | 质量优先查询平台白名单；留空时省积分模式仅在未手动指定平台时只跑 Quake，关闭省积分模式或手动指定平台时跟随启用平台 |
| `quality_query_profiles` | `["txiptv_live", "live_interface", "zhgx", "tvheadend"]` | 质量画像白名单，默认跳过近期低收益或噪声偏高的 JSMpeg、频道 API、组播代理、M3U、运营商播放列表、中间件品牌和 Xtream |
| `quality_query_profile_size` | `120` | 每个平台质量画像查询的总搜索目标量，会按已选省份和画像拆分（10-2000） |
| `quality_hotspot_enabled` | `true` | 是否启用质量热点补源，基于历史高质量源所在网段继续探测 |
| `quality_hotspot_scan_limit` | `120` | 每轮质量热点最多探测的 IP:端口候选数量（1-5000） |
| `quality_hotspot_min_score` | `8` | 质量热点网段最低入选分数（1-1000） |
| `quality_source_min_stability` | `45` | 参与质量热点学习的历史源最低稳定性（0-100） |

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

系统提供 `/api/health` 健康检查端点，供 Docker、反向代理或外部监控探测。该端点不需要 BasicAuth。

默认响应是轻量格式，只检查数据库连接、FFmpeg 可执行文件和扫描模块状态：

```json
{
  "status": "ok",
  "checks": {
    "database": "ok",
    "ffmpeg": "ok",
    "scanner": "ok"
  }
}
```

设置环境变量 `IPTV_HEALTH_DETAILED=1` 后，会额外返回版本、运行时间、磁盘、内存、最近测速、调度器和测试运行状态：

```json
{
  "status": "ok",
  "checks": {
    "database": "ok",
    "ffmpeg": "ok",
    "scanner": "ok",
    "disk": "ok"
  },
  "version": "1.6.16",
  "uptime": 123.45,
  "system": {
    "disk_percent": 38.2,
    "disk_free_gb": 120.5,
    "memory_percent": 45.2,
    "memory_available_gb": 4.8
  },
  "last_test": {
    "time": "2026-06-28 12:00:00",
    "pass_rate": 82.5,
    "total_passed": 165,
    "total_tested": 200
  },
  "scheduler": {
    "running": true,
    "next_run": "2026-06-28 18:00:00"
  },
  "test_running": false
}
```

当数据库检查失败或磁盘空间达到告警阈值时，`status` 会变为 `degraded`，HTTP 状态码返回 `503`；正常时返回 `200`。`checks.scanner` 可能返回 `ok`、`not_running`、`not_available` 或 `error`。

### 搜索查询说明

基础搜索查询定义在 `scanner_integration/config_bridge.py` 中，会按实际启用平台套用不同语法。默认关键词只保留能直接提取频道的高价值入口：

| 平台 | 默认查询语法 | 说明 |
| --- | --- | --- |
| Quake 360 | `body="..."` | 使用 `body` 搜索页面内容 |
| Hunter 鹰图 | `web.body="..."` | 使用 `web.body` 搜索网页正文 |
| DayDayMap | `body="..."` | 使用 `body` 搜索页面内容 |
| Fofa | `body="..."` | 使用 `body` 搜索页面内容 |

默认查询特征覆盖：

| 特征字符串 | 说明 |
| --- | --- |
| `/tsfile/live/` + `key=txiptv` | 最新测速中高通过率的 TXIPTV 直播源特征 |
| `/iptv/live/zh_cn.js` | 常见 IPTV 系统 JS 文件路径 |
| `/iptv/live/1000.json?key=txiptv`、`/iptv/live/1000.json` | IPTV JSON 接口特征 |
| `/ZHGXTV/Public/json/live_interface.txt` | ZHGX IPTV 直播接口特征 |

省份和运营商过滤条件会自动追加到默认查询之后（使用 `AND` / `&&` 连接）。

质量优先查询会在基础查询后追加执行画像，并继承已选省份和运营商过滤，适合 API 平台基础返回量偏少时补充更精准的候选源。默认画像由 `quality_query_profiles` 控制，当前默认跳过近期低收益或噪声偏高的 JSMpeg、频道 API、组播代理、M3U 播放列表、运营商播放列表、中间件品牌和 Xtream；如需扩大覆盖面，可以在配置 JSON 中重新加入对应 profile 名称。

| 画像 | Profile 名称 | 默认启用 | 覆盖特征 |
| --- | --- | --- | --- |
| TXIPTV 直播源 | `txiptv_live` | 是 | `/tsfile/live/` + `key=txiptv`、`/iptv/live/1000.json?key=txiptv` |
| 标准直播接口 | `live_interface` | 是 | `/iptv/live/zh_cn.js`、`/iptv/live/1000.json` |
| ZHGXTV | `zhgx` | 是 | `ZHGXTV`、`/ZHGXTV/Public/json/live_interface.txt` |
| JSMpeg | `jsmpeg` | 否 | `jsmpeg-streamer`、`/streamer/list` |
| 频道 API | `channel_api` | 否 | `getChannelList`、`/getChannelList`、`/api/channels`、`/channels`、`/channel_list.json`、`/api/live/channels`、`/live/channels.json` |
| M3U 播放列表 | `m3u_playlist` | 否 | `/playlist?profile=pass`、`#EXTM3U` + `tvg-name` |
| 组播代理 | `multicast_proxy` | 否 | `udpxy`、`/udpxy/chanlist`、`/udp/chanlist`、`/rtp/chanlist` |
| Tvheadend | `tvheadend` | 是 | `tvheadend`、`Tvheadend` 标题、`/playlist?profile=pass` |
| 中间件品牌 | `middleware_brand` | 否 | `EasyLive`、`Hybroad` |
| 运营商播放列表 | `operator_playlist` | 否 | `/migu/playlist.m3u8`、`/icntv/playlist.m3u8`、`/migu/live/`、`/icntv/live/` |
| Xtream | `xtream` | 否 | `Xtream` + `IPTV` |

每个平台的质量画像目标量由 `quality_query_profile_size` 控制，并会按已选省份和画像拆分预算；最终命中仍会经过频道提取、去重、快速过滤和深度检测。

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

**Q: 扫描到的内容很少怎么办？**
先看扫描日志里的平台级统计：`API命中` 少通常是平台配额、关键词、已选省份/运营商范围较窄或平台索引覆盖问题；`API命中` 不少但 `提取频道` 少，通常是目标不是 IPTV 播放源、接口不可访问或被快速过滤。可尝试增大 `quake_size`、`hunter_size`、`daydaymap_size`、`fofa_size`；如果只是排查覆盖面，可临时扩大省份或运营商范围；同时确认 `quality_discovery_enabled` 和 `quality_hotspot_enabled` 已开启，并让系统积累一段时间的高质量历史结果后再跑质量热点补源。

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

**Q: 如何启用质量热点补源？**
默认已启用。扫描配置里的 `quality_hotspot_enabled` 控制开关，`quality_source_min_stability` 控制参与学习的历史源稳定性门槛，`quality_hotspot_scan_limit` 控制每轮补源探测预算。该功能依赖历史持久化结果，刚部署或历史数据很少时命中会偏少。

**Q: 如何启用频道复活？**
在扫描配置中设置 `resurrection_enabled` 为 `true`，并配置 `resurrection_interval_hours`（默认 24 小时）。系统会定期尝试复活已删除的频道。

**Q: 如何配置 Webhook 通知？**
当前版本保留了通知发送工具代码，但默认系统配置、配置保存 API 和前端参数页没有开放 Webhook 字段；如需使用，需要先补齐 `DEFAULT_CONFIG`、后台表单、配置保存白名单以及对应事件触发点。

**Q: 数据库连接失败？**
Docker 部署时检查 `.env` 里的 `DB_*` 配置，并确认 MySQL 服务可被容器访问；直接运行源码且未设置 `DB_HOST` 时，检查 `database/db_config.json`。配置示例见 `database/db_config.json.example`。

**Q: 如何备份数据库？**
使用 MySQL 自带的备份工具（如 `mysqldump`）定期备份。建议在低峰期进行备份。

## 更新日志

GitHub 仓库首页默认只展示 README，不会自动展开 CHANGELOG 内容。最近更新摘要见 README 顶部“最近更新摘要”，详细版本记录请查看 [CHANGELOG.md](CHANGELOG.md)。

**重要：每次代码修改都必须将更新内容写入 [CHANGELOG.md](CHANGELOG.md) 文件；只有发布级或用户可见变更才提升版本号。** 请遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 格式规范。

## 许可证

本项目采用 [MIT 许可证](LICENSE) 开源。

## 致谢

- [TDesign Vue Next](https://tdesign.tencent.com/vue-next/overview) - 前端组件库
- [Flask](https://flask.palletsprojects.com/) - Web 后台框架
- [MySQL](https://www.mysql.com/) / [PyMySQL](https://pymysql.readthedocs.io/) - 数据库引擎
- [FFmpeg](https://ffmpeg.org/) - 音视频处理工具
- [aiohttp](https://docs.aiohttp.org/) - 异步 HTTP 客户端

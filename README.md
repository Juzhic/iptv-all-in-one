# iptv-all-in-one

IPTV 频道测速、扫描与订阅管理工具。它可以聚合 M3U 订阅源，使用 FFmpeg 检测分辨率、带宽和质量，也可以通过 Quake、Hunter、DayDayMap、Fofa 等平台发现酒店 IPTV 服务，并在 Web 控制台中管理任务、结果、历史与配置。

当前版本：**2.0.4**。完整变更见 [CHANGELOG.md](CHANGELOG.md)；从 1.x 升级必须先阅读 [MIGRATING-2.0.md](MIGRATING-2.0.md)。

## 核心能力

| 模块 | 能力 |
| --- | --- |
| 订阅测速 | 多 M3U 聚合、频道模板、别名归一、FFmpeg 分辨率/编码检测、带宽采样、TXT/M3U 输出 |
| 频道扫描 | Quake、Hunter、DayDayMap、Fofa，多 Key 轮换，质量画像查询，C 段扩展和热点补源 |
| IP 扫描 | 批量 IP/域名与端口探测，识别多种 IPTV 系统并提取频道 |
| 质量维护 | 快速检查、深度检测、定期复检、连续失败移除、频道复活和质量趋势 |
| 运维控制台 | 总览、任务、来源、结果、日志、历史和配置中心，支持桌面与移动端、浅色与深色主题 |
| 数据存储 | MySQL 保存配置、任务租约、历史、日志、扫描结果和质量数据 |

2.0 控制台默认在页面可见时轮询：任务运行中每 2 秒、空闲时每 10 秒，页面隐藏时暂停。旧 SSE 端点仅保留兼容能力。

## 安全与部署边界

- 官方应用容器以 UID `10001` 非 root 用户运行，根文件系统只读，仅 `/tmp`、`/app/data`、`/app/output` 可写。
- MySQL root 密码、应用数据库密码、BasicAuth 密码必须彼此独立；应用使用专用数据库账号 `iptv_app`。
- `IPTV_SECRET_KEY` 用于加密扫描平台 API Key，必须稳定保存，丢失后不能解密既有密文。
- Docker 模式缺少强凭据、应用仍使用 root 数据库账号或密码复用时会拒绝启动。
- Web 配置不能指定任意输出路径；运维侧只能通过 `IPTV_OUTPUT_DIR` 指定目录，文件名固定为 `result.txt`、`result.m3u`、`history.json`。
- 管理修改请求要求同源 Origin、`X-IPTV-Request: 1` 和正确的 JSON/multipart Content-Type。
- 公网请求会阻断 DNS 重绑定、回环、链路本地和云元数据地址；IP 扫描仍允许显式的 RFC1918 私网目标。

仍需注意三项明确保留的边界：

1. TXT/M3U 订阅端点保持匿名，任何能访问服务端口的客户端都可以读取。
2. Docker Compose 默认把 `58080` 绑定到所有宿主机网卡，公网部署必须配合防火墙、VPN 或反向代理。
3. Codeup 自动同步 GitHub `main` 的流程保持不变，发布仍应以 CI 门禁结果为准。

## Docker 快速开始

推荐直接使用仓库内的 [docker-compose.yml](docker-compose.yml) 和 [.env.example](.env.example)。默认会启动应用与独立的 MySQL 8.4 容器。

```bash
# 在项目根目录生成数据库、BasicAuth 和加密主密钥
python generate_env.py

# Linux 上没有 python 命令时可使用 python3
python3 generate_env.py

docker compose up -d
docker compose ps
```

访问 `http://服务器地址:58080`，使用根目录 `.env` 中的 `IPTV_AUTH_USERNAME` 和 `IPTV_AUTH_PASSWORD` 登录。

常用命令：

```bash
# 查看日志
docker compose logs -f iptv-all-in-one

# 更新镜像
docker compose pull
docker compose up -d

# 停止服务但保留数据卷
docker compose down
```

不要执行 `docker compose down -v`，该命令会删除 MySQL、应用数据和输出数据卷。

### 从 1.x 升级

升级前必须备份 MySQL 和根目录 `.env`，停止仍会写库的 1.x 任务，然后执行：

```bash
python generate_env.py --upgrade
docker compose --profile migration run --rm migrate-2-0
docker compose up -d mysql iptv-all-in-one
```

迁移会创建专用数据库账号并事务化加密旧 API Key。任一步失败都应先查看日志并恢复备份，不要删除数据表或重新生成 `IPTV_SECRET_KEY`。完整步骤、验证和回退方法见 [MIGRATING-2.0.md](MIGRATING-2.0.md)。

### 使用外部 MySQL

在 `.env` 中配置已有数据库：

```dotenv
DB_HOST=数据库地址
DB_PORT=3306
DB_NAME=iptv-all-in-one
DB_USER=iptv_app
DB_PASSWORD=独立的应用数据库密码
IPTV_AUTH_USERNAME=admin
IPTV_AUTH_PASSWORD=独立的管理密码
IPTV_SECRET_KEY=至少32字符的稳定随机密钥
```

应用账号应只拥有目标数据库权限，不能使用 root。启动命令：

```bash
docker compose -f docker-compose.external-mysql.yml up -d
```

后续查看日志、更新和停止服务时继续使用同一个 `-f docker-compose.external-mysql.yml` 参数。

### 备份与恢复

默认 MySQL 容器模式：

```bash
# 备份
docker compose exec mysql sh -c 'mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --databases "$MYSQL_DATABASE"' > iptv-all-in-one.sql

# 恢复
docker compose exec -T mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD"' < iptv-all-in-one.sql
```

数据库备份和 `.env` 都包含敏感信息，不要提交到 Git、Issue 或聊天记录。

## 配置入口

Docker/Compose 优先读取根目录 `.env`。源码运行时同样优先读取 `DB_*` 环境变量；未设置 `DB_HOST` 时才读取 `database/db_config.json`。

常用环境变量：

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `MYSQL_ROOT_PASSWORD` | MySQL 初始化和一次性迁移使用的 root 密码 | Docker 必填 |
| `DB_HOST` / `DB_PORT` | 应用数据库地址和端口 | `mysql` / `3306` |
| `DB_NAME` | 数据库名 | `iptv-all-in-one` |
| `DB_USER` / `DB_PASSWORD` | 应用专用数据库账号和密码 | `iptv_app` / Docker 必填 |
| `IPTV_AUTH_USERNAME` | Web BasicAuth 用户名 | `admin` |
| `IPTV_AUTH_PASSWORD` | Web BasicAuth 强密码 | Docker 必填 |
| `IPTV_SECRET_KEY` | API Key 加密/HMAC 主密钥，至少 32 字符 | Docker 必填 |
| `PORT` | Compose 暴露到宿主机的端口 | `58080` |
| `IPTV_OUTPUT_DIR` | 固定输出目录 | 源码 `output/`，镜像 `/app/output` |
| `IPTV_TRUSTED_ORIGINS` | 额外允许的完整 HTTP(S) Origin，逗号分隔 | 空 |
| `IPTV_INSECURE_TLS_HOSTS` | 明确允许跳过 TLS 校验的主机名；仅用于紧急兼容 | 空 |
| `IPTV_HEALTH_DETAILED` | 设为 `1` 返回详细健康信息 | 空 |
| `FFMPEG_BIN` | FFmpeg 可执行文件路径 | `ffmpeg` |

全部变量及 MySQL 小内存参数见 [.env.example](.env.example)。测速、扫描、检测、订阅、模板和别名等业务配置请在 Web 控制台的“配置中心”维护，保存后写入 MySQL。

### 文本配置格式

订阅源每行一个 HTTP(S) M3U 地址，空行和 `#` 注释会被忽略：

```text
https://example.com/a.m3u
https://example.com/b.m3u
```

别名映射第一列为主名，后续为精确别名或 `re:` 正则别名。正则匹配有 50 ms 超时保护：

```text
CCTV-1,CCTV1,CCTV-01,re:(?i)^CCTV[-_ ]?0?1.*$
CCTV-5+,CCTV5+,CCTV-5+体育赛事
```

频道模板中的 `,#genre#` 行表示分类，其余行表示需要匹配、测速和输出的频道：

```text
央视频道,#genre#
CCTV-1
CCTV-5+

卫视频道,#genre#
广东卫视
```

频道模板为空时不会产生有效测速结果。

### 运行模式

| 模式 | 行为 |
| --- | --- |
| `once` | 仅手动或命令行触发一次 |
| `times` | 按 `run_times` 中的每日时间点运行 |
| `interval` | 按 `run_interval_minutes` 间隔运行 |

## Web 控制台

| 分组 | 页面 |
| --- | --- |
| 工作台 | 总览 |
| 质量 | 扫描频道、订阅源、检测监控 |
| 任务 | 系统测试、频道扫描、IP 扫描 |
| 配置 | 历史记录、配置中心 |

配置中心内部包含“扫描配置”和“系统配置”。服务端分页页面的搜索、筛选和排序都由后端执行；导出操作会明确区分当前页和全部筛选结果。

快捷键：`Ctrl+S` 保存当前配置，`Ctrl+F` 聚焦当前页搜索，`Alt+1` 到 `Alt+9` 按导航顺序切换页面。焦点位于输入控件时不会拦截浏览器或表单按键。

## 输出与订阅

每轮通过筛选的地址写入：

```text
output/result.txt
output/result.m3u
```

| 地址 | 用途 | 是否需要 BasicAuth |
| --- | --- | --- |
| `/api/download/txt` | 下载最近结果 TXT | 否 |
| `/api/download/m3u` | 下载最近结果 M3U | 否 |
| `/api/subscribe.m3u` | 播放器订阅入口 | 否 |
| `/api/health` | 健康检查 | 否 |

`/api/subscribe.m3u` 支持 `format=txt`、`category`、`province`、`codec=h265|h264`、`min_bandwidth`、`profile` 等查询参数。匿名订阅按 IP 限流为每分钟 60 次，结果缓存 30 秒，并返回 ETag。

测速历史、任务日志和扫描结果保存在 MySQL；`history.json` 仅作为固定输出目录中的兼容文件，不是主要历史存储。

## API 2.0 摘要

多数管理 API 返回：

```json
{"ok": true, "data": {}}
```

重要接口变化：

| 接口 | 2.0 行为 |
| --- | --- |
| `GET /api/dashboard?trend_limit=10` | 返回扫描/订阅质量、趋势和任务摘要 |
| `GET /api/tasks` | 返回各任务的 `task_id/state/progress/started_at/error` |
| 各 trigger / stop 接口 | 返回 HTTP `202` 和稳定的 `task_id/state` |
| `GET /api/sources` | 服务端分页、搜索和排序，URL 默认脱敏 |
| `POST /api/discover` | 频道发现改为 POST |
| `/api/scan/keys` | 只返回 `key_id` 和后六位，不返回完整 Key |
| 配置导入导出 | 使用 `schema_version: 2`；验证失败返回 `422` 并整体回滚 |

所有 POST、PUT、PATCH、DELETE 管理请求必须携带同源 `Origin`、`X-IPTV-Request: 1` 和预期 Content-Type。浏览器前端会自动添加这些信息。

## 健康检查

```bash
curl --fail http://127.0.0.1:58080/api/health
```

默认只检查数据库、FFmpeg 和扫描模块；设置 `IPTV_HEALTH_DETAILED=1` 后额外返回运行时间、磁盘、内存、调度和最近测速摘要。正常返回 HTTP `200`，数据库或磁盘等关键检查失败时返回 `503`。

## 源码运行与开发

需要 Python 3.12、MySQL 8.4、FFmpeg；修改前端时还需要 Node.js 20。

```bash
# 后端依赖
python -m pip install -r requirements-dev.txt

# 构建前端
cd frontend
npm ci
npm run build
cd ..

# 启动 Web 服务，默认监听 58080
python -m web
```

前端热更新开发模式：

```bash
python -m web --dev
```

该命令会启动 Vite `:3000` 和 Flask API `:58080`，两端读取同一份根目录 `.env`。

测试与构建检查：

```bash
python -m pytest -q

cd frontend
npm test
npm run build
npm run check:size
```

## 常见问题

**Docker 启动后立即退出**

检查 `.env` 是否包含四个互不相同的强凭据：`MYSQL_ROOT_PASSWORD`、`DB_PASSWORD`、`IPTV_AUTH_PASSWORD`、`IPTV_SECRET_KEY`，并查看 `docker compose logs iptv-all-in-one`。

**数据库连接失败**

Docker 部署检查 `.env` 中的 `DB_*`；源码运行且未设置 `DB_HOST` 时检查 `database/db_config.json`。应用账号不能使用 root。

**页面空白或静态资源 404**

源码部署需要先执行 `cd frontend && npm ci && npm run build`。Docker 镜像已经包含前端产物。

**FFmpeg 未找到**

确认命令行能运行 `ffmpeg -version`，或用 `FFMPEG_BIN` 指向实际可执行文件。

**所有频道都不通过**

检查订阅地址、频道模板和别名是否匹配，再在配置中心适当降低最低分辨率、最低带宽或并发数。扫描板块的带宽单位为 MB/s。

**扫描结果很少**

先查看平台级收益统计：API 命中少通常是配额、关键词或区域过滤问题；命中多但提取少通常是目标接口无频道或被质量门槛过滤。质量热点补源需要先积累历史结果。

**修改旧 TXT 配置没有生效**

2.0 的订阅、模板、别名和扫描配置保存在 MySQL，请在 Web 配置中心编辑。旧 `subscribe.txt`、`alias.txt`、`demo.txt` 不再作为运行时来源。

**能否配置 Webhook**

当前只保留通知发送工具代码，默认配置、保存 API 和前端尚未开放 Webhook 字段。

## 项目结构

```text
database/             MySQL 访问、schema 与迁移
engine/               订阅解析、测速、别名与结果生成
scanner_integration/  频道/IP 扫描、复检和安全网络层
web/                  Flask 应用、API、调度与任务控制
frontend/             Vue 3 + TDesign 控制台
tests/                Python 单元与集成测试
output/               固定 TXT/M3U 输出目录
data/                 应用运行数据目录
```

## 相关文档

- [MIGRATING-2.0.md](MIGRATING-2.0.md)：1.x 到 2.0 的备份、迁移、验证和回退。
- [CHANGELOG.md](CHANGELOG.md)：完整版本记录。
- [.env.example](.env.example)：全部部署环境变量。
- [DOCKERHUB.md](DOCKERHUB.md)：Docker Hub 精简说明。
- [frontend-style-guide.md](frontend-style-guide.md)：控制台视觉与交互规范。

## 许可证与致谢

本项目采用 [MIT License](LICENSE)。感谢 Flask、Vue、TDesign、MySQL、FFmpeg、aiohttp 及相关开源项目。

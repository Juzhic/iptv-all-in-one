# iptv-all-in-one

IPTV 频道测速、扫描与订阅管理工具，支持多 M3U 聚合、FFmpeg 质量检测、Quake/Hunter/DayDayMap/Fofa 发现、定期复检以及桌面/移动端 Web 控制台。

## 快速开始

推荐下载仓库中的 `docker-compose.yml`、`.env.example` 和 `generate_env.py`，在同一目录执行：

```bash
python generate_env.py
docker compose up -d
docker compose ps
```

访问 `http://服务器地址:58080`，使用 `.env` 中的 `IPTV_AUTH_USERNAME` 与 `IPTV_AUTH_PASSWORD` 登录。

首次生成的 `.env` 包含相互独立的 MySQL root 密码、应用数据库密码、BasicAuth 密码和稳定的 `IPTV_SECRET_KEY`。应用容器以非 root 用户运行，根文件系统只读；运行时发现凭据不完整会明确告警，但不会再让升级后的服务反复退出。

常用命令：

```bash
docker compose logs -f iptv-all-in-one
docker compose pull
docker compose up -d
docker compose down
```

不要执行 `docker compose down -v`，它会删除 MySQL、应用数据和输出数据卷。

## 从 1.x 升级

2.0.5 起，未修改的 1.x `.env` 可以先直接兼容启动；即使最初 2.0 Compose 仍传入严格凭据开关，或旧数据库结构迁移需要人工处理，常驻 Web 服务也只会告警而不会循环退出：

```bash
docker compose pull
docker compose up -d
docker compose logs --tail=200 iptv-all-in-one
```

请同步下载当前 Compose 文件。镜像默认 UID 10001 可兼容最初 2.0 创建的数据卷，但旧 Compose 的必填变量解析规则不能靠拉取镜像改变。

缺少 `DB_USER` 时仍使用 root，旧数据卷也不会被强制切换为非 root/只读。若未配置 `IPTV_AUTH_PASSWORD`，日志会显示本次临时登录密码，并随重启变化。兼容启动不会自动完成安全迁移。

备份 MySQL 和根目录 `.env`、停止仍在写库的 1.x 服务后，再严格按四步迁移：

```bash
# 1. 保留活动 1.x 凭据，暂存专用应用账号
python generate_env.py --upgrade

# 2. 创建并验证账号，迁移加密旧 API Key
docker compose --profile migration run --rm migrate-2-0

# 3. 迁移成功后才激活专用账号和严格模式
python generate_env.py --finalize-upgrade

# 4. 启动 2.0
docker compose up -d mysql iptv-all-in-one
```

`--upgrade` 不改变活动的 1.x `DB_USER/DB_PASSWORD`；迁移失败时不要执行 `--finalize-upgrade`，旧 active root 凭据仍保持不变。不要删除或重新生成 `IPTV_SECRET_KEY`，否则既有加密 API Key 将无法恢复。

需要保留旧容器内的 `output/history.json`、TXT 或 M3U 时，应在删除旧容器前另行复制。

确认新输出卷属主已调整为 `10001:10001` 且可写后，运行 `python generate_env.py --enable-container-hardening` 并重建容器；不要对未核对名称的卷执行改权或删除。

如果最初 2.0 的旧升级脚本已经提前把 `.env` 切换到尚未创建的 `iptv_app`，先运行 `python generate_env.py --recover-interrupted-upgrade` 恢复两阶段暂存状态；无法识别时恢复升级前 `.env` 备份。

MySQL 用户 DDL 不能事务回滚。脚本只会在本轮新建账号且后续步骤失败时尝试补偿删除；配置和 API Key 更新使用数据库事务保护。已有同名账号不会被自动改密，必须保证现有密码与暂存密码一致，或改用新的账号名。完整步骤见项目仓库中的 `MIGRATING-2.0.md`。

## 外部 MySQL

在根目录 `.env` 中填写外部数据库信息：

```dotenv
DB_HOST=数据库地址
DB_PORT=3306
DB_NAME=iptv-all-in-one
DB_USER=iptv_app
DB_PASSWORD=独立的应用数据库密码
IPTV_AUTH_USERNAME=admin
IPTV_AUTH_PASSWORD=独立的管理密码
IPTV_SECRET_KEY=至少32字符的稳定随机密钥
IPTV_REQUIRE_STRONG_CREDENTIALS=1
```

应用账号应只拥有目标数据库权限，不能使用 root。启动时使用：

```bash
docker compose -f docker-compose.external-mysql.yml up -d
```

后续 `pull`、`logs`、`ps` 和 `down` 也要继续带同一个 `-f` 参数。从 1.x 外部数据库升级时，应由管理员在受控环境运行一次性迁移，不要把 root 开放到公网。

## 主要功能

- 聚合多个 M3U 订阅源，按频道模板和别名精准匹配。
- FFmpeg 分辨率、编码与带宽检测，支持质量评分和定时运行。
- Quake、Hunter、DayDayMap、Fofa 多平台扫描与多 Key 轮换。
- C 段扩展、质量热点补源、IP/端口扫描和多 IPTV 系统识别。
- 持久结果定期检测、连续失败移除、频道复活和趋势统计。
- MySQL 数据存储，任务租约、历史、日志与配置统一管理。
- Vue 3 + TDesign 控制台，适配桌面/移动端与浅色/深色主题。

## 关键环境变量

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `MYSQL_ROOT_PASSWORD` | 仅 MySQL 初始化与一次性迁移使用 | 必填 |
| `DB_HOST` / `DB_PORT` | 应用数据库地址和端口 | `mysql` / `3306` |
| `DB_USER` / `DB_PASSWORD` | 应用专用数据库账号和密码 | `iptv_app` / 必填 |
| `DB_NAME` | 数据库名 | `iptv-all-in-one` |
| `IPTV_AUTH_USERNAME` | Web BasicAuth 用户名 | `admin` |
| `IPTV_AUTH_PASSWORD` | Web BasicAuth 强密码 | 必填 |
| `IPTV_SECRET_KEY` | API Key 加密/HMAC 主密钥 | 必填 |
| `IPTV_CONTAINER_USER` | 容器 UID/GID；新部署生成器设为 `10001:10001` | 旧版兼容为 `root` |
| `IPTV_HARDENED_CONTAINER` | 只读根文件系统开关 | 旧版兼容为 `false` |
| `PORT` | 宿主机访问端口 | `58080` |
| `IPTV_OUTPUT_DIR` | 固定结果目录 | `/app/output` |

## 输出与安全提示

固定输出文件为 `result.txt`、`result.m3u` 和 `history.json`。播放器可使用 `/api/subscribe.m3u` 订阅，也可以访问 `/api/download/txt` 与 `/api/download/m3u`。

TXT/M3U 订阅端点有每 IP 限流、缓存和 ETag，但仍保持匿名。Compose 默认将 `58080` 发布到所有宿主机网卡；请使用防火墙、VPN 或反向代理限制可达范围。`IPTV_SECRET_KEY` 必须与数据库和 `.env` 备份一起稳定保存。

## 技术栈

Python 3.12 / Flask / Gunicorn / aiohttp / PyMySQL / Vue 3 / TDesign / Vite / MySQL 8.4 / FFmpeg / Docker Compose

# iptv-all-in-one

IPTV 频道测速、扫描与订阅管理工具，支持多 M3U 聚合、FFmpeg 质量检测、频道/IP 扫描、定期复检，以及桌面和移动端 Web 控制台。

当前版本：**2.1.1**。从 1.x 升级请先阅读 [MIGRATING-2.0.md](MIGRATING-2.0.md)，完整版本记录见 [CHANGELOG.md](CHANGELOG.md)。

## 主要功能

- 聚合多个 M3U 订阅，按模板和别名筛选频道。
- 检测分辨率、编码、带宽、延迟与稳定性，并生成 TXT/M3U。
- 通过 Quake、Hunter、DayDayMap、Fofa 发现 IPTV 服务。
- 批量扫描 IP、网段和端口，识别常见 IPTV 系统。
- 定期复检、移除失效频道、恢复可用频道并记录质量趋势。
- 在 Web 控制台统一管理总览、质量、任务、历史、日志和配置。

## Docker 快速开始

下载仓库中的 `docker-compose.yml`、`.env.example` 和 `generate_env.py`，放在同一目录后执行：

```bash
python generate_env.py
docker compose up -d
docker compose ps
```

如果系统只有 `python3`，请替换上面的 `python`。访问 `http://服务器地址:58080`，使用 `.env` 中的 `IPTV_AUTH_USERNAME` 和 `IPTV_AUTH_PASSWORD` 登录。

生成器会创建彼此独立的 MySQL root 密码、应用数据库密码、管理密码和 `IPTV_SECRET_KEY`。全新部署默认使用非 root 用户和只读根文件系统。

```bash
# 查看日志
docker compose logs -f iptv-all-in-one

# 更新
docker compose pull
docker compose up -d
```

不要执行 `docker compose down -v`，它会删除数据库、应用数据和输出数据卷。

## 从 1.x 升级

2.0.5 起，旧 `.env` 可先以兼容模式启动，不会仅因使用 root 数据库账号、缺少新增凭据或旧库迁移告警而反复退出。兼容模式会保留完整告警，但不会自动完成账号、结构和密钥迁移。

升级前必须备份 MySQL 与 `.env`，然后严格按以下顺序执行：

```bash
# 1. 保留当前数据库连接并暂存新凭据
python generate_env.py --upgrade

# 2. 创建专用账号并加密旧 API Key
docker compose --profile migration run --rm migrate-2-0

# 3. 迁移成功后激活新账号和加固模式
python generate_env.py --finalize-upgrade

# 4. 启动应用
docker compose up -d mysql iptv-all-in-one
```

迁移失败时不要执行 `--finalize-upgrade`，也不要删除或重新生成 `IPTV_SECRET_KEY`。若早期 2.0 脚本已提前切换到尚未创建的账号，可运行 `python generate_env.py --recover-interrupted-upgrade`。完整的备份、验证、卷权限和回退步骤见 [MIGRATING-2.0.md](MIGRATING-2.0.md)。

## 配置

Docker/Compose 从根目录 `.env` 读取配置，业务参数在 Web 控制台的“配置中心”维护。常用环境变量如下，完整清单见 [.env.example](.env.example)。

| 变量 | 用途 |
| --- | --- |
| `MYSQL_ROOT_PASSWORD` | MySQL 初始化和一次性迁移 |
| `DB_HOST` / `DB_PORT` | 数据库地址和端口 |
| `DB_USER` / `DB_PASSWORD` | 应用数据库账号和密码 |
| `IPTV_AUTH_USERNAME` / `IPTV_AUTH_PASSWORD` | Web 登录凭据 |
| `IPTV_SECRET_KEY` | API Key 加密与 HMAC 主密钥 |
| `PORT` | Web 端口，默认 `58080` |
| `IPTV_OUTPUT_DIR` | 固定结果目录，默认 `/app/output` |
| `IPTV_INSECURE_TLS_HOSTS` | 明确允许跳过 TLS 校验的遗留主机 |

使用外部 MySQL 时填写 `.env`，并始终使用专用数据库账号：

```bash
docker compose -f docker-compose.external-mysql.yml up -d
```

后续 `pull`、`logs`、`ps` 和 `down` 也要带同一个 `-f` 参数。

## 输出与订阅

结果固定写入 `IPTV_OUTPUT_DIR` 下的 `result.txt`、`result.m3u` 和 `history.json`。

| 地址 | 用途 |
| --- | --- |
| `/api/subscribe.m3u` | M3U/TXT 订阅，支持分类、地区、编码和质量筛选 |
| `/api/download/txt` | 下载最近 TXT 结果 |
| `/api/download/m3u` | 下载最近 M3U 结果 |
| `/api/health` | 健康检查 |

## 安全边界

- 全新部署使用强凭据、专用数据库账号、非 root 用户和只读根文件系统。
- 扫描平台 API Key 使用稳定的 `IPTV_SECRET_KEY` 加密；该密钥必须随数据库一起备份。
- 公网复检会阻断回环、链路本地、云元数据和 DNS 重绑定目标；TLS 失败不会自动降级。
- 匿名订阅有每 IP 限流、30 秒缓存和 ETag，但任何能访问服务端口的客户端仍可读取播放列表。
- Compose 默认把 `58080` 绑定到所有网卡，公网部署请使用防火墙、VPN 或反向代理限制访问。

## 源码运行与测试

需要 Python 3.12、MySQL 8.4、FFmpeg；修改前端还需要 Node.js 20。

```bash
python -m pip install -r requirements-dev.txt

cd frontend
npm ci
npm run build
cd ..

python -m web
```

```bash
python -m pytest -q

cd frontend
npm test
npm run build
npm run check:size
```

前端热更新可运行 `python -m web --dev`。生产环境建议保持单进程多线程 Gunicorn，避免任务状态分散到多个进程。

## 常见问题

| 现象 | 首要检查 |
| --- | --- |
| Docker 启动后退出 | `docker compose logs --tail=200 iptv-all-in-one` |
| 页面无法登录 | `.env` 中的登录信息；旧部署临时密码见启动日志 |
| 数据库连接失败 | `.env` 中的 `DB_*` 和现有 MySQL volume 的真实密码 |
| 页面空白或静态资源 404 | 源码部署是否已执行前端构建 |
| 扫描结果过少 | 订阅、模板、别名、平台配额、区域筛选和质量阈值 |

## 相关文档

- [MIGRATING-2.0.md](MIGRATING-2.0.md)：1.x 升级、验证与回退。
- [CHANGELOG.md](CHANGELOG.md)：完整版本记录。
- [.env.example](.env.example)：全部环境变量。
- [DOCKERHUB.md](DOCKERHUB.md)：Docker Hub 部署说明。
- [frontend-style-guide.md](frontend-style-guide.md)：控制台视觉与交互规范。

本项目采用 [MIT License](LICENSE)。

# IPTV All in One

IPTV 频道测速、候选源采集、健康复检和 TXT/M3U 播放列表管理工具。

当前版本：**3.0.2**。3.0 起数据库已切换为 PostgreSQL，旧 MySQL 数据卷不能直接复用。完整升级步骤见 [MIGRATING-3.0.md](MIGRATING-3.0.md)，版本记录见 [CHANGELOG.md](CHANGELOG.md)。

## 主要能力

- 订阅源聚合、频道别名匹配和 FFmpeg 质量检测
- Quake、Hunter 等候选源采集与持久化质量维护
- 定时测速、历史对比、数据来源质量和任务状态管理
- TXT/M3U 输出、筛选订阅、缓存、ETag 和每 IP 限流
- Web 配置中心、BasicAuth、敏感 API Key 加密
- PostgreSQL 18、Docker Compose 和 amd64/arm64 镜像

## 飞牛 OS 单 YAML 部署

仓库中的 `docker-compose.yml` 是不含真实秘密的公开模板。先在可信电脑生成一份私有部署文件：

```bash
python generate_fnos_compose.py
```

脚本会生成 `docker-compose.fnos.yml`，其中已经写入相互独立的 PostgreSQL 管理员密码、应用数据库密码、Web 登录密码和稳定 `IPTV_SECRET_KEY`，但不会在终端打印这些值。目标飞牛 OS 只需要上传这一份 YAML。

在飞牛 Docker Compose 项目中选择该文件，或在命令行运行：

```bash
docker compose -f docker-compose.fnos.yml up -d
```

访问 `http://飞牛IP:58080`，登录账号为 YAML 中的 `IPTV_AUTH_USERNAME`，密码为 `IPTV_AUTH_PASSWORD`。

注意：

- `docker-compose.fnos.yml` 等同于密码文件，必须私密保存并纳入灾备，禁止提交到 Git。
- 不要执行 `docker compose down -v`，否则会删除 PostgreSQL、应用数据和输出卷。
- 应用固定发布在宿主机 `58080`；PostgreSQL 仅绑定 `127.0.0.1:5432`。
- 应用连接数据库时始终使用 Docker 内网地址 `postgres:5432`，不会绕行宿主端口。
- PostgreSQL 的 `db_host_access` bridge 只用于使宿主回环映射生效；应用和初始化任务仍仅通过 `db_internal` 与数据库通信。
- 如需 FRP，请自行转发宿主机端口；本项目不内置或配置 frpc/frps。

## 从 2.x 升级

3.0 是破坏性数据库升级。MySQL 数据目录和 `mysql_data` 卷不能挂载给 PostgreSQL，也不能把 mysqldump 直接交给 `psql`。

升级前必须同时保留：

1. MySQL 逻辑备份；
2. 旧 `.env` 和稳定的 `IPTV_SECRET_KEY`；
3. 2.1.2 镜像、Compose 和原 MySQL 数据卷；
4. 应用输出目录的独立备份。

先启动全新的 PostgreSQL 3.0 栈，再在维护窗口执行受控的数据恢复。恢复验证通过前不要删除或改写旧 MySQL 卷。详细校验和回滚步骤见 [MIGRATING-3.0.md](MIGRATING-3.0.md)。历史 1.x → 2.x 说明仍保留在 [MIGRATING-2.0.md](MIGRATING-2.0.md)。

## 运行配置

飞牛私有 YAML 已包含生产所需配置，不再依赖 `.env`。常用变量如下：

| 变量 | 用途 | 默认值 |
| --- | --- | --- |
| `DB_HOST` / `DB_PORT` | 应用使用的 PostgreSQL 内网地址 | `postgres` / `5432` |
| `DB_USER` / `DB_PASSWORD` | PostgreSQL 非管理员应用账号 | `iptv_app` / 私有随机值 |
| `DB_NAME` | PostgreSQL 数据库名 | `iptv_all_in_one` |
| `IPTV_AUTH_USERNAME` / `IPTV_AUTH_PASSWORD` | Web 登录凭据 | `admin` / 私有随机值 |
| `IPTV_SECRET_KEY` | API Key 加密与 HMAC 主密钥 | 私有随机值 |
| `IPTV_TRUSTED_ORIGINS` | 允许变更请求的额外完整 HTTP(S) Origin | 空 |
| `IPTV_INSECURE_TLS_HOSTS` | 紧急兼容时允许跳过 TLS 校验的主机 | 空 |
| `IPTV_OUTPUT_DIR` | 固定结果目录 | `/app/output` |
| `IPTV_REQUIRE_DATABASE` | 数据库不可用时拒绝启动 | `1` |
| `IPTV_REQUIRE_STRONG_CREDENTIALS` | 弱凭据时拒绝启动 | `1` |

PostgreSQL 管理员凭据只提供给数据库和一次性初始化服务，常驻应用不会收到管理员密码。

## 输出与订阅

结果固定写入 `IPTV_OUTPUT_DIR` 下的 `result.txt`、`result.m3u` 和 `history.json`。

| 地址 | 用途 | 认证 |
| --- | --- | --- |
| `/api/subscribe.m3u` | 可筛选的 M3U/TXT 订阅 | 匿名 |
| `/api/download/txt` | 下载最近 TXT 结果 | 匿名 |
| `/api/download/m3u` | 下载最近 M3U 结果 | 匿名 |
| `/api/health` | 健康检查 | 匿名 |
| Web 管理页及其他 API | 配置、扫描与历史管理 | BasicAuth |

## 安全边界

- PostgreSQL 使用 SCRAM 密码认证，管理员与 `iptv_app` 分离，5432 默认只对宿主回环开放。
- Docker Engine 28.0.0 之前存在 localhost 发布端口仍可能被同一二层网络访问的[已知限制](https://github.com/moby/moby/issues/45610)；飞牛使用旧版 Engine 时必须再加宿主防火墙规则。
- 应用以 UID/GID 10001 运行，根文件系统只读，移除 Linux capabilities，并启用 `no-new-privileges`。
- `IPTV_SECRET_KEY` 必须与 PostgreSQL 备份一起稳定保存；丢失后既有加密 API Key 无法恢复。
- 58080 会发布到飞牛宿主网络。通过 FRP 暴露前，应为浏览器入口配置 HTTPS、访问控制和正确的 `IPTV_TRUSTED_ORIGINS`。
- FRP 传输加密不等于浏览器到公网入口的 HTTPS。
- 匿名订阅有速率限制和缓存，但任何能访问 58080 的客户端仍可读取播放列表。
- 不要把 PostgreSQL 5432 直接绑定到 `0.0.0.0`；如需远程维护，使用临时且受认证、受防火墙保护的隧道。

## 源码运行与测试

需要 Python 3.12、PostgreSQL 18、FFmpeg；修改前端还需要 Node.js 20。

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q

cd frontend
npm ci
npm test
npm run build
npm run check:size
```

源码运行时可通过 `database/db_config.json` 或显式 `DB_*` 环境变量连接开发 PostgreSQL。前端热更新使用 `python -m web --dev`。生产环境保持单进程、多线程 Gunicorn，避免任务状态分散到多个进程。

## 常见问题

| 现象 | 首要检查 |
| --- | --- |
| Compose 启动后退出 | `docker compose -f docker-compose.fnos.yml logs --tail=200` |
| PostgreSQL 初始化失败 | 数据卷是否为全新 PG18 卷、私有 YAML 四个秘密是否完整 |
| 页面无法登录 | 私有 YAML 中的 `IPTV_AUTH_USERNAME` / `IPTV_AUTH_PASSWORD` |
| 变更请求返回 403 | 公网最终 Origin 是否加入 `IPTV_TRUSTED_ORIGINS` |
| 页面空白或静态资源 404 | 镜像标签是否为 3.0.2，源码部署是否完成前端构建 |
| 候选源过少 | 测绘平台配额、区域筛选、关键词和质量阈值 |

## 相关文档

- [MIGRATING-3.0.md](MIGRATING-3.0.md)：MySQL → PostgreSQL 升级、恢复与回滚。
- [MIGRATING-2.0.md](MIGRATING-2.0.md)：历史 1.x → 2.x 迁移说明。
- [DOCKERHUB.md](DOCKERHUB.md)：镜像部署和运维说明。
- [CHANGELOG.md](CHANGELOG.md)：完整版本记录。

## License

[MIT](LICENSE)

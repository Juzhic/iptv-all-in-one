# IPTV All in One Docker 部署

镜像：`juzhic/iptv-all-in-one`

- `3.0.2`：固定的 PostgreSQL 18 版本
- `latest`：当前稳定版
- 平台：`linux/amd64`、`linux/arm64`

3.0 起应用仅支持 PostgreSQL，不再支持 MySQL 连接或旧 MySQL 数据卷。

## 飞牛 OS / Docker Compose

公开 `docker-compose.yml` 包含完整的 PostgreSQL、账号初始化和应用服务，但其中的四个凭据是不可用于生产的占位符。在可信电脑运行：

```bash
python generate_fnos_compose.py
```

生成的 `docker-compose.fnos.yml` 已内置独立随机密码和稳定密钥，部署端只需要这一份文件：

```bash
docker compose -f docker-compose.fnos.yml pull
docker compose -f docker-compose.fnos.yml up -d
docker compose -f docker-compose.fnos.yml ps
```

不要把私有 YAML 上传到公开仓库，也不要在终端、工单或日志中粘贴其环境变量。轮换 `IPTV_SECRET_KEY` 会让已加密的扫描 API Key 无法解密。

## 服务与网络

| 服务 | 用途 | 暴露范围 |
| --- | --- | --- |
| `postgres` | PostgreSQL 18 数据库 | 宿主 `127.0.0.1:5432` |
| `postgres-init` | 幂等创建/更新 `iptv_app` 与授权 | 一次性、无端口 |
| `iptv-all-in-one` | Web、扫描和播放列表 | 宿主 `0.0.0.0:58080` |

应用通过专用 Docker 内网连接 `postgres:5432`。数据库不加入应用出网网络；它单独连接 `db_host_access` bridge 以使宿主回环端口映射生效。应用另接普通 bridge 网络，以便访问订阅、测绘平台和视频源。

PostgreSQL 18 的持久卷挂载点是 `/var/lib/postgresql`。不要照搬旧版本教程改为 `/var/lib/postgresql/data`，也不要执行 `docker compose down -v`。

## 账号与凭据

- `iptv_admin` 是 PostgreSQL 初始化管理员，只提供给数据库和一次性初始化服务。
- `iptv_app` 是常驻应用账号，不具备超级用户、建角色或建库权限。
- PostgreSQL 主机认证使用 SCRAM-SHA-256。
- Web 使用 `IPTV_AUTH_USERNAME` / `IPTV_AUTH_PASSWORD` BasicAuth。
- `IPTV_REQUIRE_DATABASE=1` 和 `IPTV_REQUIRE_STRONG_CREDENTIALS=1` 会在数据库或凭据不安全时拒绝启动。

如确需轮换数据库密码，先备份私有 YAML 和 PostgreSQL，再使用当前管理员会话在 `psql` 中通过交互式 `\password iptv_app` / `\password iptv_admin` 修改角色密码，随后同步修改 YAML 中该密码的所有对应位置并重建服务。只改 `POSTGRES_PASSWORD` 环境变量不会更新已有数据卷中的角色密码。不要直接用生成器覆盖现有文件；`--force` 会同时轮换四个秘密，仅适用于确认废弃旧凭据的全新部署。`IPTV_SECRET_KEY` 不应随普通密码轮换，否则既有加密 API Key 将无法解密。

## 端口与 FRP

应用端口 `58080` 面向飞牛宿主网络发布。项目不内置 frpc/frps；可以按自己的网络方案转发 58080。

PostgreSQL 仅绑定宿主回环 `127.0.0.1:5432`，用于本机管理或宿主级安全隧道。不要直接改成 `0.0.0.0:5432`。如通过 FRP 提供数据库维护入口，应同时限制来源、启用强 token/TLS，并在操作完成后关闭隧道。

Docker Engine 28.0.0 之前存在 localhost 发布端口仍可能被同一二层网络访问的[已知限制](https://github.com/moby/moby/issues/45610)。飞牛使用旧版 Engine 时必须配置宿主防火墙限制 5432，不能只依赖回环绑定。

浏览器公网入口需要独立的 HTTPS。FRP transport TLS 只保护 frpc 到 frps，不会自动为浏览器提供 HTTPS。反向代理后的最终 Origin 应加入 `IPTV_TRUSTED_ORIGINS`。

## 匿名接口

以下接口为了兼容 IPTV 客户端保持匿名：

- `/api/subscribe.m3u`
- `/api/download/txt`
- `/api/download/m3u`
- `/api/health`

订阅接口带限流、缓存和 ETag，但任何能到达 58080 的客户端仍可读取播放列表。公网部署应通过反向代理、VPN、防火墙或 FRP 访问控制限制可达范围。

## 从 2.x 迁移

旧 MySQL dump 不能直接由 `psql` 恢复，MySQL 数据卷也不能改名后交给 PostgreSQL。升级前保留：

- 完整 MySQL 逻辑备份
- 旧 `.env` 与 `IPTV_SECRET_KEY`
- 2.1.2 镜像和 Compose
- 原 MySQL 数据卷及应用输出

先创建全新的 3.0 PostgreSQL 卷，再单独迁移和校验数据。恢复通过前不要删除旧环境。完整步骤见仓库的 `MIGRATING-3.0.md`。

## PostgreSQL 备份

建议定期同时备份 PostgreSQL 和私有 YAML：

```bash
docker compose -f docker-compose.fnos.yml exec -T postgres \
  pg_dump -U iptv_admin -d iptv_all_in_one -Fc > iptv-postgres.dump
```

执行恢复、删除卷或跨 PostgreSQL major 升级前，必须先验证备份可读。`postgres:18` 只跟随 18.x 修复版本；未来升级 PostgreSQL 19 必须使用官方升级流程，不能只改镜像标签。

## 运行状态

```bash
docker compose -f docker-compose.fnos.yml logs --tail=200 postgres
docker compose -f docker-compose.fnos.yml logs --tail=200 postgres-init
docker compose -f docker-compose.fnos.yml logs --tail=200 iptv-all-in-one
curl --fail http://127.0.0.1:58080/api/health
```

应用容器以 UID/GID 10001、只读根文件系统、`cap_drop: ALL` 和 `no-new-privileges` 运行；只有 `/app/data`、`/app/output` 与受限 `/tmp` 可写。

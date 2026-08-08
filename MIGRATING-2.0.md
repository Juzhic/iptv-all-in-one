# 升级到 IPTV-Test 2.0

IPTV-Test 2.0 是一次包含安全模型、API 契约、数据库账号和管理界面的破坏性升级。升级前必须备份 MySQL 和根目录 `.env`，并安排维护窗口。不要在迁移完成前启动 2.0 应用服务。

## 升级前检查

1. 停止会写入数据库的旧版应用和定时任务。
2. 导出完整 MySQL 备份，并验证备份文件可以读取。
3. 复制根目录 `.env` 到安全位置。`IPTV_SECRET_KEY` 是解密扫描平台 API Key 的唯一主密钥，丢失后无法恢复密文。
4. 记录当前镜像标签、Compose 文件和数据库卷名称，以便必要时回退。
5. 确认主机可以运行 Python 3.12，或准备使用 2.0 镜像中的一次性迁移服务。

示例备份命令中的容器名、数据库名和路径需要按实际部署调整：

```bash
docker compose stop iptv-all-in-one
docker exec mysql mysqldump -uroot -p --single-transaction --routines --triggers iptv-all-in-one > iptv-before-2.0.sql
cp .env .env.before-2.0
```

不要把 `.env` 或数据库备份提交到 Git，也不要把其中的密码粘贴到日志、Issue 或聊天记录。

## Docker Compose 升级

先更新 2.0 的代码、`docker-compose.yml` 和镜像，然后在项目根目录执行：

```bash
python generate_env.py --upgrade
docker compose --profile migration run --rm migrate-2-0
docker compose up -d mysql iptv-all-in-one
```

`generate_env.py --upgrade` 会执行以下操作：

- 把 1.x 中原本作为 MySQL root 密码使用的 `DB_PASSWORD` 原值保存为 `MYSQL_ROOT_PASSWORD`。
- 生成独立的应用数据库密码、BasicAuth 密码和 `IPTV_SECRET_KEY`。
- 把应用账号改为 `iptv_app`，并原子写入 `.env`；类 Unix 系统上的权限会设为 `0600`。
- 保留已有配置和值，不在终端输出任何凭据。

一次性 `migrate-2-0` 服务会暂时读取 root 密码，创建并授权专用应用账号，验证该账号可以连接，然后事务化加密旧扫描平台 API Key。常驻 `iptv-all-in-one` 容器不会收到 root 密码。

如果 `.env` 已经使用非 root 专用账号，只需运行 `python generate_env.py` 补齐缺少的强凭据；仍建议执行迁移命令，让旧明文 API Key 完成加密。

## 源码或外部 MySQL 部署

外部 MySQL 必须先完成数据库备份，并允许迁移命令临时以 MySQL root 账号连接。准备好包含以下变量的根目录 `.env`：

```text
DB_HOST=数据库地址
DB_PORT=3306
DB_NAME=iptv-all-in-one
DB_USER=iptv_app
DB_USER_HOST=%
DB_PASSWORD=独立的应用密码
MYSQL_ROOT_PASSWORD=数据库 root 密码
IPTV_AUTH_USERNAME=admin
IPTV_AUTH_PASSWORD=独立的管理密码
IPTV_SECRET_KEY=至少 32 字符的稳定随机密钥
```

安装 2.0 依赖后执行：

```bash
python migrate_2_0.py --env-file .env
```

迁移成功后，从常驻服务的环境中移除 `MYSQL_ROOT_PASSWORD`，只保留应用账号。外部 MySQL 如果禁止 root 远程连接，应由数据库管理员在受控环境运行迁移命令；不要临时开放 root 到公网。

## 验证升级

```bash
docker compose ps
curl --fail http://127.0.0.1:58080/api/health
docker compose logs --tail=200 iptv-all-in-one
```

随后完成以下人工检查：

- 使用 `.env` 中新的 BasicAuth 凭据登录管理界面。
- 总览可以显示扫描质量、订阅质量、趋势和任务摘要。
- `/api/tasks` 中没有遗留的活动租约；触发和停止任务后 `task_id` 保持一致。
- 扫描平台 Key 只显示 `key_id` 与后六位，接口和浏览器网络面板中没有完整 Key。
- `result.txt`、`result.m3u` 和 `history.json` 写入 `IPTV_OUTPUT_DIR` 对应的输出卷。
- 匿名 TXT/M3U 订阅仍可由播放器访问，并返回缓存、ETag 和限流响应头。

## 失败与回退

迁移命令任一步失败都会以非零状态退出。新建的应用数据库账号会被清理，配置、API Key 和扫描记录不会被部分覆盖；应用启动时的 schema 或密钥迁移失败也会拒绝启动。

失败后先保留日志并修复原因，再从备份重试。需要回退到 1.x 时：

1. 停止 2.0 容器。
2. 恢复升级前的 MySQL 备份。
3. 恢复 `.env.before-2.0`，因为 1.x 仍把旧 `DB_PASSWORD` 当作 root 密码。
4. 恢复旧 Compose 文件和旧镜像标签后再启动。

不要通过删除数据库表、清空配置或重新生成 `IPTV_SECRET_KEY` 来“修复”迁移失败。`generate_env.py --force` 会轮换数据库和管理密码，但会保留已有 `IPTV_SECRET_KEY`，避免现有密文失效。

## 2.0 兼容性变化

- Web 配置和导入导出不再接受 `output_txt`、`output_m3u`；运维侧仅能通过 `IPTV_OUTPUT_DIR` 选择输出目录，文件名固定。
- 配置导入导出使用 `schema_version: 2`，无效配置返回 `422` 且不产生部分写入。
- `GET /api/discover` 改为 `POST /api/discover`。
- 任务触发/停止接口返回 HTTP `202` 和顶层 `task_id/state`；状态统一从 `/api/tasks` 恢复。
- `/api/scan/keys` 的更新和删除改用 `key_id`，不再返回完整密钥。
- 来源与检测结果筛选、排序、分页改为服务端执行；“当前页导出”和“全部筛选结果导出”语义分离。

## 明确保留的残余风险

2.0 没有改变以下部署选择：

- TXT/M3U 订阅地址继续匿名开放，任何能访问服务端口的人都可以读取播放列表。
- Docker 默认仍将 `58080` 发布到所有宿主机网卡。
- Codeup 自动同步 `main` 的工作流保持不变。

2.0 通过订阅限流和缓存、强凭据、非 root/只读容器与发布门禁降低风险，但不能替代防火墙、VPN、反向代理访问控制和升级前备份。

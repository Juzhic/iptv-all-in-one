# 升级到 IPTV-Test 2.0

IPTV-Test 2.0 改变了安全模型、API 契约、数据库账号和管理界面。2.0.5 起，未修改的 1.x `.env` 会先以兼容模式启动，不再仅因旧凭据而退出；即使最初 2.0 Compose 仍传入严格开关，凭据问题也只会告警。要启用专用账号和 API Key 加密，仍应安排维护窗口并采用“暂存账号 → 数据库迁移 → 激活账号”的两阶段流程。不要在迁移成功前手工覆盖活动数据库凭据。

升级镜像时也应同步更新本版本的 Compose 文件。镜像默认 UID 10001 可继续访问最初 2.0 创建的卷，但旧 Compose 自身的必填变量插值无法由镜像修复；若 `docker compose config` 已报缺变量，请先更新 Compose，不要删除数据卷。

如果当前目标只是先恢复服务，可更新 Compose 与 2.0.5 或更高镜像后执行。常驻 Web 进程对凭据、旧结构和 API Key 迁移问题只告警，不会因此循环退出；一次性迁移命令仍会严格失败，禁止在失败后执行 finalize：

```bash
docker compose up -d
docker compose logs --tail=200 iptv-all-in-one
```

缺少 `IPTV_AUTH_PASSWORD` 时，日志会显示本次临时登录凭据；容器重启后密码会变化。兼容启动不会自动切换数据库账号，也不代表安全迁移已经完成。

## 升级前检查

1. 停止会写入数据库的旧版应用和定时任务。
2. 导出完整 MySQL 备份，并验证备份文件可以读取。
3. 复制根目录 `.env` 到安全位置。
4. 记录旧镜像标签、Compose 文件和数据库卷名称，以便回退。
5. 确认可以使用数据库 root/管理员凭据执行一次性账号迁移。
6. 如需保留旧容器内的 `output/history.json`、TXT 或 M3U，在删除旧容器前复制出来；1.x 默认 Compose 没有持久化该目录。

示例中的容器名、数据库名和路径需要按实际部署调整：

```bash
docker compose stop iptv-all-in-one
docker exec mysql mysqldump -uroot -p --single-transaction \
  --routines --triggers iptv-all-in-one > iptv-before-2.0.sql
cp .env .env.before-2.0
```

`.env` 和数据库备份都包含秘密，不要提交到 Git，也不要粘贴到日志、Issue 或聊天记录。`IPTV_SECRET_KEY` 是解密扫描平台 API Key 的唯一主密钥；迁移开始后必须稳定保存，不能通过删除或重新生成它来处理故障。

## Docker Compose：四步两阶段迁移

先更新 2.0 的代码、`docker-compose.yml` 和镜像，然后在项目根目录严格按顺序执行：

```bash
# 1. 暂存：保留活动 1.x 凭据，生成待验证的专用应用账号
python generate_env.py --upgrade

# 2. 迁移：创建/验证专用账号，迁移加密旧 API Key
docker compose --profile migration run --rm migrate-2-0

# 3. 激活：仅在迁移命令成功后切换活动账号并启用严格模式
python generate_env.py --finalize-upgrade

# 4. 启动：使用已经验证的专用账号，暂时保留兼容容器权限
docker compose up -d mysql iptv-all-in-one
```

如果系统只有 `python3` 命令，请将 `python` 替换为 `python3`。

如果你曾运行最初发布的 2.0 `generate_env.py --upgrade`，随后因应用账号尚未创建而无法连接数据库，请先停止容器并执行：

```bash
python generate_env.py --recover-interrupted-upgrade
```

该命令仅在 `.env` 同时保留旧 `MYSQL_ROOT_PASSWORD` 与提前生成的非 root `DB_USER/DB_PASSWORD` 时工作：它把非 root 凭据移入暂存字段，恢复旧 root 活动连接，然后再按上面的第 2～4 步继续。识别不明确时命令拒绝写入；此时必须恢复 `.env.before-2.0`，不要手工猜密码。

### 第一阶段：暂存，不切换活动凭据

`generate_env.py --upgrade` 会：

- 把 1.x 当前使用的 root 密码保存在 `MYSQL_ROOT_PASSWORD`。
- 在 `IPTV_MIGRATION_DB_USER` 和 `IPTV_MIGRATION_DB_PASSWORD` 中暂存新的专用账号。
- 补齐缺少的 BasicAuth 密码和稳定的 `IPTV_SECRET_KEY`。
- 暂时保持 `IPTV_REQUIRE_STRONG_CREDENTIALS=0`，允许旧 root-only 布局在迁移准备阶段兼容启动。
- 原子写入 `.env`，类 Unix 系统上设置为 `0600`，且不在终端打印凭据。

关键保证：活动的 `DB_USER/DB_PASSWORD` 在这一步保持 1.x 原值，不会提前切换。若数据库迁移尚未成功，旧服务仍可以使用原活动 root 凭据回退。

### 数据库迁移：验证后再处理配置

一次性 `migrate-2-0` 服务会临时接收 root 密码，并依次：

1. 确认目标数据库存在。
2. 创建专用应用账号并授权目标数据库。
3. 使用暂存账号实际连接数据库，验证密码和权限。
4. 通过应用数据库连接迁移旧扫描平台 API Key 的加密存储。

迁移完成并 finalize 后，常驻 `iptv-all-in-one` 容器不再使用 root 账号；一次性迁移服务才接收 `MYSQL_ROOT_PASSWORD`。兼容启动阶段的 `DB_PASSWORD` 仍是旧 root 密码。

如果 `DB_USER_HOST` 下已经存在同名 MySQL 账号，迁移不会更改该账号的密码。必须预先保证它的现有密码与 `IPTV_MIGRATION_DB_PASSWORD` 一致，或改用一个新的专用账号名；验证失败时保持活动 1.x 凭据不变，不要执行下一步。

### 第二阶段：激活已验证账号

只有迁移命令以状态码 0 完成后，才执行：

```bash
python generate_env.py --finalize-upgrade
```

该命令不会轮换任何秘密，而是把已经验证的暂存账号写入活动 `DB_USER/DB_PASSWORD`，同步初始化字段，清空暂存字段，并把 `IPTV_REQUIRE_STRONG_CREDENTIALS` 设为 `1`。随后才可以启动 2.0 应用。

`--finalize-upgrade` 不会自动切换容器 UID 或只读模式，因为旧 bind mount/volume 可能仍由 root 持有。先验证 `/app/data`、`/app/output` 可写，再由运维把实际卷或绑定目录属主调整为 `10001:10001`，然后运行：

```bash
python generate_env.py --enable-container-hardening
```

重建应用容器后检查 UID、健康状态和结果写入。卷名受 Compose project name 影响；先用 `docker compose config --volumes` 核对，禁止凭猜测执行删除或改权命令。

## 为什么不能声称“迁移整体事务回滚”

MySQL 用户 DDL（如 `CREATE USER`、`GRANT`）不能与配置表更新一起整体提交或回滚。当前迁移边界是：

- 本轮新建账号后若后续步骤失败，脚本会尝试 `DROP USER` 进行补偿清理；如果清理也失败，会输出明确警告，需要管理员人工核对。
- 已经存在的同名账号不属于本轮创建，不会在失败时删除，也不会被自动改密。
- 配置和旧 API Key 的读取/加密更新由应用数据库事务保护，失败时不会提交部分配置写入。
- `.env` 的活动 1.x `DB_USER/DB_PASSWORD` 直到 `--finalize-upgrade` 才切换，因此迁移失败时仍保留原活动 root 凭据。

这不是跨 MySQL DDL、配置数据和文件系统的全局事务。升级前的数据库与 `.env` 备份仍是最终回退保障。

## 外部 MySQL 或源码部署

外部 MySQL 也必须完成备份，并允许迁移命令在受控环境临时以 root/数据库管理员身份连接。不要为了迁移临时把 root 开放到公网。

对旧 root-only `.env`，仍先运行：

```bash
python generate_env.py --upgrade
```

确认根目录 `.env` 至少包含：

```dotenv
DB_HOST=数据库地址
DB_PORT=3306
DB_NAME=iptv-all-in-one
DB_USER=root
DB_PASSWORD=旧版当前活动的root密码
DB_USER_HOST=%
MYSQL_ROOT_PASSWORD=旧版当前活动的root密码
IPTV_MIGRATION_DB_USER=iptv_app
IPTV_MIGRATION_DB_PASSWORD=脚本生成的暂存应用密码
IPTV_AUTH_USERNAME=admin
IPTV_AUTH_PASSWORD=独立的管理密码
IPTV_SECRET_KEY=至少32字符的稳定随机密钥
```

安装 2.0 依赖后执行：

```bash
python migrate_2_0.py --env-file .env
python generate_env.py --finalize-upgrade
```

第二条命令只能在第一条成功后执行。完成后，常驻服务只保留专用账号；不要把 `MYSQL_ROOT_PASSWORD` 注入应用进程。外部 MySQL 的 Compose 启动方式为：

```bash
docker compose -f docker-compose.external-mysql.yml up -d
```

如果部署原本已经使用非 root 专用账号，不需要把它降级成 root-only 布局。先运行 `python generate_env.py` 补齐缺少的强凭据；若数据库仍有明文 API Key，应由管理员按实际账号状态安排一次性迁移并验证，避免覆盖已有账号密码。

## 验证升级

```bash
docker compose ps
curl --fail http://127.0.0.1:58080/api/health
docker compose logs --tail=200 iptv-all-in-one
```

随后人工确认：

- `.env` 中 `DB_USER` 已是专用非 root 账号，`IPTV_REQUIRE_STRONG_CREDENTIALS=1`，暂存字段为空。
- 如果已经显式启用容器加固，进程 UID 为 `10001`、根文件系统只读，且 `/app/data` 与 `/app/output` 可写。
- 使用新的 BasicAuth 凭据可以登录管理界面。
- 总览可以显示扫描质量、订阅质量、趋势和任务摘要。
- `/api/tasks` 没有遗留活动租约；触发和停止任务后 `task_id` 一致。
- 扫描平台 Key 只显示 `key_id` 与后六位，接口和浏览器网络面板不出现完整 Key。
- `result.txt`、`result.m3u` 和 `history.json` 写入 `IPTV_OUTPUT_DIR` 对应的输出卷。
- 匿名 TXT/M3U 订阅仍可访问，并返回缓存、ETag 和限流响应头。

## 失败处理与回退

任一步失败都应停止后续步骤，保留命令输出并确认当前阶段：

- `--upgrade` 失败：原子写入不会留下半份 `.env`；使用备份检查原配置。
- 最初 2.0 的旧 `--upgrade` 已提前切换账号：使用 `--recover-interrupted-upgrade` 恢复暂存状态；无法识别时恢复升级前 `.env` 备份。
- `migrate-2-0` 失败：不要执行 `--finalize-upgrade`。活动 1.x 凭据仍不变；核对是否遗留了本轮新建账号以及配置事务状态后再重试。
- `--finalize-upgrade` 失败：不要手工拼接或替换密码；迁移已验证的暂存值仍应保留，修复文件权限或格式后重试。
- 2.0 启动失败：检查严格凭据、专用账号权限、健康检查和容器日志。

需要完整回退到 1.x 时：

1. 停止 2.0 容器。
2. 恢复升级前的 MySQL 备份。
3. 恢复 `.env.before-2.0`，因为 1.x 仍把旧 `DB_PASSWORD` 当作 root 密码。
4. 恢复旧 Compose 文件和旧镜像标签后再启动。

不要通过删除数据库表、清空配置、手工复制暂存密码或重新生成 `IPTV_SECRET_KEY` 来“修复”迁移。即使使用 `generate_env.py --force`，也应先理解它会轮换数据库/管理密码；脚本会刻意保留已有 `IPTV_SECRET_KEY`，避免现有密文失效。

## 2.0 兼容性变化

- Web 配置和导入导出不再接受 `output_txt`、`output_m3u`；运维侧只能通过 `IPTV_OUTPUT_DIR` 选择输出目录，文件名固定。
- 配置导入导出使用 `schema_version: 2`；无效配置返回 `422`，配置数据不产生部分写入。
- `GET /api/discover` 改为 `POST /api/discover`。
- 任务触发/停止接口返回 HTTP `202` 和顶层 `task_id/state`；状态从 `/api/tasks` 恢复。
- `/api/scan/keys` 的更新与删除使用 `key_id`，不再返回完整密钥。
- 来源与检测结果的筛选、排序、分页在服务端执行；当前页导出与全部筛选结果导出语义分离。

## 明确保留的残余风险

2.0 没有改变以下部署选择：

- TXT/M3U 订阅地址继续匿名开放，任何能访问服务端口的人都可以读取播放列表。
- Docker 默认仍将 `58080` 发布到所有宿主机网卡。
- Codeup 自动同步 GitHub `main` 的工作流保持不变。

订阅限流与缓存、强凭据、非 root/只读容器和发布门禁只能降低风险，不能替代防火墙、VPN、反向代理访问控制以及升级前验证过的备份。

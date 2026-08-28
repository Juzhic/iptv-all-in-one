# 从 2.x MySQL 迁移到 3.0 PostgreSQL

3.0 将唯一运行时数据库切换为 PostgreSQL 18。该升级不会自动读取 MySQL dump，不会复用 MySQL 卷，也不会双写两个数据库。

## 已知备份

仓库工作区中的 `iptv_backup.sql` 是 MySQL 8.4.10 mysqldump：

- 大小：229,569,224 字节
- SHA-256：`2C5E6746F9B98FBA0ADC2554027F96866FDC913A667594700A68C5AFDABBB9CD`
- 表数：21
- 记录数：约 1,173,728

它包含 MySQL 专属 DDL、反引号、InnoDB、字符排序规则、前缀索引和 extended INSERT，不能直接交给 `psql`。文件还包含业务 URL、配置及潜在凭据，必须按敏感备份管理，不能提交到 Git 或打入应用镜像。

## 升级前检查

在停止 2.1.2 前，至少保留以下可独立恢复的副本：

1. 使用 `mysqldump --single-transaction` 生成并校验的 MySQL 逻辑备份；
2. 原 MySQL 数据卷的存储级快照；
3. 旧 `.env`、稳定 `IPTV_SECRET_KEY` 和扫描平台配置；
4. 2.1.2 的镜像标签、Compose 文件和应用输出卷；
5. 当前运行状态、表数量和关键业务页面截图或导出。

恢复演练完成前，不要删除、改名、重新初始化或交给 PostgreSQL 挂载原 MySQL 卷。

## 部署 PostgreSQL 3.0

在可信电脑生成私有 Compose：

```bash
python generate_fnos_compose.py
```

然后在一个全新的 Compose 项目中启动：

```bash
docker compose -f docker-compose.fnos.yml up -d
docker compose -f docker-compose.fnos.yml ps
```

新栈使用独立 `postgres_data` 卷，PostgreSQL 18 挂载 `/var/lib/postgresql`。应用通过 `postgres:5432` 内网连接；宿主 5432 只绑定回环地址。

空库启动完成后应验证：

- `postgres` 为 healthy；
- `postgres-init` 成功退出；
- 应用 `/api/health` 正常；
- 应用账号不是 PostgreSQL 超级用户；
- 重启 Compose 后 schema 初始化幂等且卷中数据仍存在。

## 数据恢复边界

本版本不附带自动 MySQL 导入器。拿到目标 PostgreSQL 地址、网络授权和维护窗口后，再单独实现并执行一次性恢复任务。恢复工具不得成为应用启动依赖，也不得长期保存数据库管理员凭据。

恢复任务必须满足：

1. 校验源文件大小和 SHA-256，拒绝未知或变化的 dump；
2. 只向经过确认的空目标库写入，禁止覆盖已有业务数据；
3. 按显式表/列映射处理 MySQL 转义、NULL、中文、emoji 和多行文本；
4. 使用批量 COPY 或等价流式方式，避免把约 219 MiB 文件整体载入内存；
5. 数据失败时整体回滚，不执行 dump 中的 MySQL DDL、账号或锁表语句；
6. 导入显式 ID 后，把每个 identity sequence 调整到 `MAX(id)+1`；
7. 将旧 `scheduler_state`、运行进度和活动任务租约归一化为停止/过期状态；
8. 重新执行 PostgreSQL 约束、索引和 `ANALYZE`。

MySQL `utf8mb4_unicode_ci` 通常按不区分大小写、部分不区分重音的规则比较文本；本项目 PostgreSQL 18 默认使用 `C.UTF-8`，普通文本唯一约束和排序是区分大小写的。程序生成的任务 ID 风险较低，但恢复工具仍必须在写入前按旧 MySQL 规则检查潜在等价值（例如仅大小写或重音不同的键），输出冲突清单并由运维确认映射，不能静默保留为两个新值。恢复验收也应分别核对唯一性、搜索和排序结果，不能只比较行数。

## 恢复验收

当前备份的重点基线为：

| 表 | 约计记录数 |
| --- | ---: |
| `quality_history` | 868,757 |
| `run_results` | 154,561 |
| `run_logs` | 86,512 |
| `detection_results` | 35,232 |
| `scan_results` | 23,250 |
| `persistent_scan_results` | 3,681 |

实际恢复时仍以源库现场统计为准，并至少校验：

- 21 张业务表逐表 `COUNT(*)`、主键最小/最大值和唯一数；
- 四组父子关系无孤儿，级联删除约束有效；
- `config_data` 六个预期键及内容哈希一致；
- `scan_results(scan_id,url)` 和 URL 哈希唯一索引无冲突；
- 最新 run、scan、detection 及中文/正则配置抽样一致；
- MySQL 与 PostgreSQL 排序规则差异造成的大小写、重音等价值冲突已清零或有人工确认记录；
- 新建任务、配置读写、历史分页、总览小数统计和播放列表输出正常；
- PostgreSQL 与整套 Compose 重启后不会重新导入或丢失数据。

备份中未发现 `enc:v1:` 前缀，但若线上 2.x 已使用稳定 `IPTV_SECRET_KEY`，3.0 必须继续使用同一密钥。发现明文第三方 API Key 或 URL token 时，应在恢复完成后轮换。

## 回滚

数据恢复或应用验收失败时：

1. 停止 3.0 应用写入；
2. 保留失败现场、PostgreSQL 日志和新卷，不在未知状态下反复重跑导入；
3. 恢复原 2.1.2 Compose、旧 `.env`、原 MySQL 卷和稳定 `IPTV_SECRET_KEY`；
4. 验证旧应用健康、定时任务和播放列表后再恢复业务入口。

3.0 与 2.1.2 之间不提供双写或自动反向同步。切换后产生的新 PostgreSQL 数据不会自动回灌 MySQL。

## PostgreSQL 灾备

生产环境应同时备份 PostgreSQL、自身生成的私有 `docker-compose.fnos.yml` 和应用输出卷。数据库逻辑备份可在不中断读取的情况下执行：

```bash
docker compose -f docker-compose.fnos.yml exec -T postgres \
  pg_dump -U iptv_admin -d iptv_all_in_one -Fc > iptv-postgres.dump
```

备份文件与私有 YAML 必须分开加密保存，并记录 PostgreSQL 18 的具体修复版本、备份时间和 SHA-256。私有 YAML 中稳定的 `IPTV_SECRET_KEY` 是解密既有扫描 API Key 的必要材料，不能只保存数据库 dump；数据库管理员密码也不得写入备份脚本日志。

至少按既定 RPO 周期执行逻辑备份，并定期在隔离的空数据库或全新 Compose 项目中演练恢复：

1. 先用 `pg_restore --list iptv-postgres.dump` 验证归档可读；
2. 创建由 `iptv_app` 持有的空验收库，再使用 `pg_restore --exit-on-error --no-owner --role=iptv_app` 恢复；
3. 核对 21 张业务表行数、外键、URL 摘要索引、identity 序列、配置哈希和匿名订阅；
4. 重启 PostgreSQL 与应用，确认 schema 初始化幂等、加密配置可读且任务状态正常；
5. 记录实际恢复耗时，并确认满足 RTO 后再销毁隔离验收环境。

存储卷快照只能作为逻辑备份的补充。除非存储平台明确提供 PostgreSQL 一致性快照，否则应先停止应用写入并按平台要求停库后再拍摄。正式灾难恢复优先创建新栈并恢复到新卷，完成验收后再切换入口，禁止在唯一存量卷上反复试恢复。

## PostgreSQL 后续升级

`postgres:18` 会跟随 18.x 安全和修复版本，不会自动跨到 19。未来 major 升级必须另做备份恢复或 `pg_upgrade` 演练，不能直接把持久卷交给不同 major 镜像。

通过 FRP 暂时开放 PostgreSQL 时，应只在维护窗口启用受认证、受限来源的隧道，完成后立即关闭。不要把宿主映射改成公开的 `0.0.0.0:5432`。Docker Engine 28.0.0 之前存在 localhost 发布端口仍可能被同一二层网络访问的[已知限制](https://github.com/moby/moby/issues/45610)，飞牛使用旧版 Engine 时必须再配置宿主防火墙限制 5432。

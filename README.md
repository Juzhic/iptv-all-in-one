# IPTV All in One

IPTV 频道测速、候选源采集、健康复检和 TXT/M3U 播放列表管理工具。

当前版本：**3.5.0**。3.0 起数据库已切换为 PostgreSQL，旧 MySQL 数据卷不能直接复用。完整升级步骤见 [MIGRATING-3.0.md](MIGRATING-3.0.md)，版本记录见 [CHANGELOG.md](CHANGELOG.md)。

## 主要能力

- 订阅源聚合、频道别名匹配和 FFmpeg 质量检测
- Quake、Hunter 等候选源采集与持久化质量维护
- 定时测速、历史对比、数据来源质量和任务状态管理
- TXT/M3U 输出、筛选订阅、缓存、ETag 和每 IP 限流
- 测速订阅在线播放、频道搜索与分类、多线路切换，支持 HLS / HTTP-TS / FLV
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

3.0.3 起使用 PostgreSQL 内置 SHA-256，无需安装 `pgcrypto`，支持未提供该扩展的宝塔 PostgreSQL 18。应用账号需拥有目标数据库及应用 schema 的建表、建函数和索引权限；业务表和摘要函数由应用启动时自动创建。升级已有 3.0 数据库时，会在事务中重建四个旧 URL 摘要索引，大数据量部署应预留首次启动的维护时间；迁移失败会回滚，不会删除已有 `pgcrypto` 扩展。

## FOFA 配置

在“配置中心 → 采集配置 → API Key 管理”添加 FOFA Key 即可，邮箱为兼容旧配置保留的选填项。“刷新余额”调用[官方账号接口](https://fofa.info/api/info)，分别显示 F 币、F 点、免费 F 点和月度 API 剩余次数/条数；`0` 表示零余额，`-` 表示接口未提供该值。Key 有效仅表示账号鉴权通过，实际搜索仍受会员权限和配额限制。

搜索参数遵循[官方查询接口](https://fofa.info/api)。运营商筛选按 FOFA `org` 字段匹配常见组织名称，覆盖范围取决于 FOFA 的 ASN 归属数据；需要尽可能完整的结果时可选择“全部运营商”。

## UDPXY 组播采集

3.5.0 新增“配置中心 → 采集配置 → UDPXY 组播采集”，默认关闭。保存后随下一轮手动/定时、全量/增量采集执行，沿用上方省份和运营商筛选；结果进入现有逐条快速检测、深测、候选池复检和订阅输出。

使用方式：

1. 开启组播采集和“使用内置模板”。内置 36 组省份/运营商模板，页面可展开查看覆盖范围；这是 spider-iptv 的 2024 年历史快照，实际可用性需要检测。
2. 自动发现：在采集平台中选择 Quake，配置已有 Quake Key，并开启“Quake 自动发现”。组播搜索单独计算预算，会消耗 Quake 额度；默认每轮最多请求 60 条结果，在模板组之间分配。小预算下模板组按日轮转，不会修改主查询和质量画像预算。
3. 手动发现：填写 `广东,电信,http://你的公网IP:端口`，每行一个。可关闭 Quake 自动发现，此时组播部分不调用搜索 API。代理必须为公网 IP 的 HTTP(S) 基础地址，可含 `/udpxy` 前缀，不支持域名、内网、账号、查询参数或完整频道播放路径。
4. 内置频道表过期或缺少目标地区时，添加自定义模板，选择省份和电信/联通/移动，粘贴 TXT（`频道名称,rtp://239.x.x.x:端口`）或 M3U。支持 UDP、RTP 和已有 HTTP 代理格式；同省份/运营商的自定义模板替换内置模板。每组最多 128000 字符、2000 个唯一目的地址，最多 32 组、合计 512000 字符。

每轮默认最多探测 20 个代理与模板组合、生成 500 条频道候选，手动代理优先，各可用代理轮流分配频道预算。最多 5 个代理并发探测，搜索限时 60 秒、整个组播采集限时 120 秒；达到限额保留已验证结果。停止操作遵循现有采集任务控制。

状态页可用只说明代理服务存在，不能证明频道可播；程序会抽检最多 3 个分散的模板频道，至少一个返回 MPEG-TS 才展开模板，然后对生成的线路逐条执行现有质量检测。状态页不可用时仍尝试流抽检。HTTP 200、模板上的“高清”名称以及其他频道的测速结果都不作为质量通过依据。同省份/运营商的网络也可能使用不同频道表，可用自定义模板调整。

模板只提取组播目的地址，忽略文件中的广告、旧代理主机、HTML 错误页和重复项，不会自动下载外部模板。源数据及 Apache-2.0 许可证随镜像包含在 `scanner_integration/data/spider_iptv/`，详细来源见 [模板说明](scanner_integration/data/spider_iptv/NOTICE.md)。

## 输出与订阅

结果固定写入 `IPTV_OUTPUT_DIR` 下的 `result.txt`、`result.m3u` 和 `history.json`。

| 地址 | 用途 | 认证 |
| --- | --- | --- |
| `/api/subscribe.m3u` | 可筛选的 M3U/TXT 订阅 | 匿名 |
| `/api/download/txt` | 下载最近 TXT 结果 | 匿名 |
| `/api/download/m3u` | 下载最近 M3U 结果 | 匿名 |
| `/api/health` | 健康检查 | 匿名 |
| Web 管理页及其他 API | 配置、扫描与历史管理 | BasicAuth |

## 在线播放测速订阅

打开“全量测速” → “播放列表订阅地址”，点击 M3U 订阅地址旁的“在线播放”，选择频道即可播放。可搜索频道、筛选分类、切换线路，视频自带音量和全屏控制。“刷新列表”重新读取 `/api/subscribe.m3u`，与外部播放器订阅保持一致（短时缓存可能稍有延迟）。

播放器支持 HLS（M3U8）、HTTP-TS、FLV 及浏览器原生视频；无后缀地址默认按 HLS 尝试，可手动切换格式。默认直连试看，支持原生 HLS 的浏览器优先使用原生播放，视频流量不经过本项目服务器。直连失败、连接超时，或 HTTPS 页面无法直连 HTTP 线路时，会自动尝试一次代理播放，无需点击；代理也失败时显示错误，不会循环切换。自动播放被浏览器拦截时仍提示点击视频播放按钮，不会因此开启代理。

代理无需源站提供跨域许可，HTTPS 管理页也可播放 HTTP 线路。页面会显示“代理播放 · 使用服务器 / FRP 带宽”；可点击“停止代理，改为直连”，显式停止后即使直连失败也不会重新自动开启代理。切换频道、线路或格式后恢复“优先直连、失败自动代理”。服务器必须能访问源站，代理视频流量会占用服务器及反向代理/FRP 的带宽；前置代理应关闭播放响应缓冲并允许长连接。关闭播放器或离开测速页会停止播放。

播放代理只允许最新测速通过的公网 HTTP(S) 线路，禁止内网、回环和云元数据地址；HLS 子列表、视频分片和密钥会自动转为签名代理地址。播放地址有效期为 12 小时，过期后点击“重新播放”；默认最多同时转发 4 个上游连接，连接上限或网络故障时可稍后重试。支持单段 Range，暂不支持 HLS 变量引用，忽略可选的 CDN steering 扩展。H.265 和部分音频编码仍取决于浏览器支持，代理不转码；无法播放时可切换线路或复制原地址到 VLC 等外部播放器。

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

Docker 发布默认执行前后端测试、PostgreSQL 集成测试和原生镜像 Compose 冒烟验证，通过后构建并发布 amd64/arm64 镜像。体积预算、数据库重启演练和 Trivy 漏洞扫描默认跳过；需要完整检查时，在 GitHub Actions 手动运行 `Quality Gate` 并勾选 `full_checks`，或在 `Test and Publish Docker Image` 中勾选该选项后检查并发布。

## 常见问题

| 现象 | 首要检查 |
| --- | --- |
| Compose 启动后退出 | `docker compose -f docker-compose.fnos.yml logs --tail=200` |
| PostgreSQL 初始化失败 | 数据卷是否为全新 PG18 卷、私有 YAML 四个秘密是否完整 |
| 页面无法登录 | 私有 YAML 中的 `IPTV_AUTH_USERNAME` / `IPTV_AUTH_PASSWORD` |
| 变更请求返回 403 | 公网最终 Origin 是否加入 `IPTV_TRUSTED_ORIGINS` |
| 页面空白或静态资源 404 | 镜像标签是否为 3.5.0，源码部署是否完成前端构建 |
| 候选源过少 | 测绘平台配额、区域筛选、关键词和质量阈值 |

## 相关文档

- [MIGRATING-3.0.md](MIGRATING-3.0.md)：MySQL → PostgreSQL 升级、恢复与回滚。
- [MIGRATING-2.0.md](MIGRATING-2.0.md)：历史 1.x → 2.x 迁移说明。
- [DOCKERHUB.md](DOCKERHUB.md)：镜像部署和运维说明。
- [CHANGELOG.md](CHANGELOG.md)：完整版本记录。

## License

[MIT](LICENSE)

随附的 spider-iptv 组播模板按 [Apache-2.0](scanner_integration/data/spider_iptv/LICENSE) 分发，来源与使用方式见 [模板说明](scanner_integration/data/spider_iptv/NOTICE.md)。

### 采集配置与接口核对

Hunter 余额仅调用 `/openApi/userInfo`，搜索调用 `/openApi/search`。采集任务使用启动时的配置，后续保存影响下一轮；关闭“每天”并清空星期可停用定时采集。各平台主查询数量按每个省份计算，画像预算另计。详细配置作用范围、8 月 24 日版本对比和关键词说明见 [采集配置审计](docs/collection-config-audit.md)。

在“配置中心 → 采集配置 → API Key 管理”中点击对应 Key 的“测试可用性”，可分别查看账号和真实搜索结果。每次使用已保存的主查询关键词请求最多 1 条，可能消耗平台额度；不会访问搜索结果中的源站。返回 0 条仍表示搜索接口可用；超时或限流会显示无法确认，而不是 Key 失效。

3.3.0 的推荐搜索规则覆盖 8 条酒店 IPTV、直播频道 JSON 列表和 Tvheadend 特征，TXIPTV 不再限定固定 key。历史默认 4 条/5 条配置自动升级；自定义配置可点击“补充推荐规则”后保存。关键词扩大候选来源，实际质量仍由测速和复检判断；“质量优先查询”按接口类型分配既有总预算，不因新增类型提高总预算。

FOFA 返回 `[820031] F点余额不足` 表示当前请求需要的 F 点不足，不足以证明免费或月度 API 额度全部耗尽。3.3.1 起该错误不会全局停用 Key；“测试可用性”会在账号结果中展示各项余额，再用同一查询请求 1 条结果。网页免费查询权益、免费 F 点、API 次数和返回条数不能直接等同。

3.4.0 在“采集配置 → 复检后自动拓展”提供候选池自动补源：定时/手动复检后，以本轮质量达标的公网 IPv4 HTTP 源为种子，探测同 C 段原端口；不使用搜索 API。默认每轮最多 50 IP、2 个网段/端口、50 条新候选深测，24 小时冷却，120 秒限时。新频道通过深测后入池并保留来源平台。该开关与 C 段总开关均开启才生效；冷却记录跨重启保留，HTTPS、域名和内网源暂不作为种子。

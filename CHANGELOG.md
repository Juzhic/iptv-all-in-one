# 更新日志

所有重要更改都会记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

**重要说明：每次代码修改都必须将更新内容写入本文件；只有发布级或用户可见变更才提升版本号。**

## [1.6.16] - 2026-06-28

### 改进
- README 按当前项目实现重新校准描述，区分 Docker `.env` 与源码直跑 `database/db_config.json` 的数据库配置入口。
- README 修正 `/api/health` 默认轻量响应和 `IPTV_HEALTH_DETAILED=1` 详细响应示例，移除旧版 `ok/data` 与 `1.6.3` 示例。
- README 修正 Gunicorn 端口说明、API 响应格式例外、结果订阅端点、输出文件示例、Web 标签页和项目结构说明。
- README 移除 Webhook 作为后台可直接启用功能的描述，改为说明当前仅保留通知发送工具代码，默认配置链路尚未开放。

## [1.6.15] - 2026-06-27

### 安全
- 移除 Docker Compose 默认 MySQL root 弱密码，`DB_PASSWORD` 未设置时会拒绝启动，避免误用固定默认密码。
- 新增 `generate_env.py`，可自动生成带随机 `DB_PASSWORD` 的 `.env`，并避免默认覆盖已有数据库密码。

### 运维
- `.env.example` 改为留空 `DB_PASSWORD` 并提示生成随机密码，部署打包脚本同步带上 `.env.example` 和 `generate_env.py`。
- README 同步更新随机密码生成流程、飞牛 Compose 示例和当前版本号。
- README 新增 GitHub 首页可见的最近更新摘要，并补充默认 MySQL Docker volume 持久化、备份、恢复和 `docker compose down -v` 风险说明。

## [1.6.14] - 2026-06-27

### 运维
- 默认 Docker Compose 内置 MySQL 新增宿主机本地端口映射，仅监听 `127.0.0.1:${MYSQL_HOST_PORT:-3306}`，便于本机数据库客户端访问且不暴露到局域网或公网。
- `.env.example` 新增 `MYSQL_HOST_PORT`，可在宿主机 3306 被占用时调整本地映射端口。
- README 同步更新 MySQL 本地访问说明、飞牛 Compose 示例和当前版本号。

## [1.6.13] - 2026-06-27

### 运维
- 默认 Docker Compose 内置 MySQL 容器名从 `iptv-mysql` 调整为 `mysql`，与服务名保持一致，避免额外的项目名前缀。
- README 同步更新默认 MySQL 容器命名、飞牛 Compose 示例和当前版本号。

## [1.6.12] - 2026-06-27

### 运维
- 默认 Docker Compose 内置 MySQL 启用轻量启动参数，关闭 Performance Schema，并收紧 InnoDB 缓冲池、日志缓冲、连接数和表缓存，降低小内存服务器上的基础内存占用。
- `.env.example` 新增默认 MySQL 容器内存相关调优项，用户可按服务器规格覆盖缓冲池、连接数和缓存大小。
- README 同步更新默认 MySQL 低内存配置说明、飞牛 Compose 示例和当前版本号。

## [1.6.11] - 2026-06-27

### 修复
- 快速过滤通过但尚未深度测速的频道不再用空字符串填充 `delay`、`bandwidth`，避免 MySQL 严格模式把 DOUBLE 字段写入判为异常。
- 统一测速结果、检测结果、质量历史和 IP 扫描响应时间等 DOUBLE 字段的写库归一化，空值、异常字符串和非有限数会写入 `NULL` 或 `0`。
- 修复单条持久化检测写入质量历史时重复获取数据库写锁，可能导致检测流程卡住的问题。

## [1.6.10] - 2026-06-26

### 改进
- 省积分模式仅在未手动指定扫描平台时收缩到 Quake；关闭省积分模式或手动指定平台时，质量优先查询会跟随所有启用渠道执行。
- 扫描配置页文案补充 Fofa，并将关闭省积分模式说明调整为适合每日免费额度充足的多渠道扫描场景。

### 运维
- Docker Compose 默认 MySQL 镜像从 `mysql:8` 收窄为 `mysql:8.4`，明确使用 MySQL 8.4 LTS 版本线，避免浮动标签带来的部署版本不确定。
- README 同步更新默认 MySQL 容器说明和当前版本号。

## [1.6.9] - 2026-06-26

### 新增
- 质量优先查询新增 `txiptv_live` 画像，专门搜索 `/tsfile/live/` 与 `key=txiptv` 组合以及 `1000.json?key=txiptv` 入口。

### 改进
- 根据最近一次测速结果收缩默认扫描策略：默认画像调整为 `txiptv_live`、`live_interface`、`zhgx`、`tvheadend`，默认画像预算从 240 降为 120。
- 基础搜索关键词移除 JSMpeg、频道 API 等低优先级入口，优先保留能产出高质量 `/tsfile/live/*.m3u8?key=txiptv` 源的特征。
- 省积分模式下默认跳过独立 JSMpeg 扫描，避免在最新测速未证明高收益的画像上继续消耗搜索积分。

## [1.6.8] - 2026-06-26

### 改进
- 频道扫描新增“省积分模式”，未手动指定平台时优先使用 Quake，并跳过隐藏的 Hunter/Tvheadend/IPTV互动等低收益补扫。
- 基础搜索关键词收敛为直播 JSON、ZHGX、JSMpeg、频道 API 等直接可提取入口，移除泛品牌、泛标题、M3U、运营商播放列表和 Xtream 等默认 OR 关键词。
- 质量优先查询默认仅使用 Quake 平台，并默认移除最近日志低收益或噪声偏高的 M3U 播放列表、运营商播放列表、中间件品牌、Xtream 画像，减少无产出的 API 查询。
- 频道扫描页优化按钮状态与文案：“开始扫描”会随启动/运行状态变化，启动后同时启用状态轮询兜底，“强制清除状态”改为“重置卡死状态”并补充适用场景。

### 修复
- 修复扫描快速过滤通过后，`delay`、`bandwidth` 等 DOUBLE 字段写入空字符串导致 MySQL 报 `Incorrect DOUBLE value` 并把扫描标记为失败的问题。
- 最近扫描失败时，频道扫描页会在进度与概览中展示失败原因，避免只看到空闲或重启重置状态。

## [1.6.7] - 2026-06-26

### 改进
- 优化扫描结果页“按扫描记录”视图：首次进入默认选中最近一轮扫描，筛选栏新增“最新一轮”“全部记录”快捷切换、加载状态和结果数量反馈。

### 修复
- 修复扫描记录下拉未兼容 `/api/scan/history` 返回的 `items` 字段，导致只能看到“全部扫描记录”的问题。

## [1.6.6] - 2026-06-26

### 改进
- 优化 `/api/initial` 首屏数据接口：默认仅返回总览所需摘要数据，不再重复返回最新测速明细和频道聚合明细，将当前数据集下的首包响应从约 3.29 MB 降至约 15 KB。
- 保留 `/api/initial?include_details=1` 兼容开关，用于需要旧版完整明细负载的调用场景。

## [1.6.5] - 2026-06-26

### 新增
- 扫描模块新增质量优先查询：在 Quake、Hunter、DayDayMap、Fofa 基础查询之外，追加标准直播接口、ZHGXTV、JSMpeg、频道 API、M3U、组播代理、Tvheadend、运营商播放列表等高价值画像查询。
- 新增质量热点补源：根据历史频道的稳定性、延迟、带宽和质量状态识别高价值 /24 网段，并围绕稳定源继续探测。
- 扫描配置页新增质量优先查询、画像查询预算、质量热点补源、热点探测预算、最低稳定性等高级扫描策略配置项。
- 新增 `web/routes/params.py`，统一路由整数参数的默认值、上下限和异常输入处理。

### 改进
- API 平台采集日志改为展示目标量、API 命中、实际探测、频道提取和 C 段补充数量，便于判断扫描结果偏少的具体环节。
- 基础搜索与质量优先查询会先整体包裹 OR 查询，再追加省份和运营商过滤，避免过滤条件只作用到最后一个关键词。
- 基础搜索关键词改为结构化生成，补充 `/channels`、`channel_list.json`、`/api/live/channels`、`/live/channels.json`、`/playlist?profile=pass`、`udpxy/udp/rtp chanlist`、咪咕和 ICNTV 播放列表等可被提取器识别的入口。
- 质量优先查询继承已选省份配置，并按省份和画像拆分 `quality_query_profile_size` 预算。
- `quality_query_profile_size` 默认值从 120 调整为 240，以适配更多画像和多省份扫描。
- Hunter 支持独立的 `hunter_size` 目标量配置，不再复用 Quake 的扫描数量。
- 扩展平台解析与提取缓存，减少重复抓取并提升 IPTV 接口、频道 API、播放地址的提取覆盖。
- `/api/health` 默认返回轻量健康信息，可通过 `IPTV_HEALTH_DETAILED=1` 开启磁盘、内存和调度等详细检查。
- Docker/Gunicorn 默认使用单 worker，避免后台扫描、SSE 和停止信号在多进程下状态不一致。
- README 补充质量优先发现、质量热点补源、扫描偏少排查和新增扫描参数说明。
- README 完善 Docker 部署教程，明确默认 MySQL 容器、外部 MySQL 和端口映射的使用方式。
- README 补充说明 `docker pull` 只下载镜像，不会启动应用或 MySQL，避免误解部署命令。
- README 新增飞牛 fnOS 图形界面部署说明，提供可直接粘贴的 Compose 配置。
- 新增 `docker-compose.external-mysql.yml`，支持只启动应用容器并连接用户已有的 MySQL。

### 修复
- 修复 MySQL 索引创建在部分版本或重复迁移时可能失败的问题。
- 修复扫描、历史、检测和 IP 扫描接口中分页、limit、rate limit 等参数缺少边界保护的问题。
- 修复前端扫描结果、历史详情和 IP 扫描页面在异常参数或长轮询场景下的刷新与状态处理问题。
- 修复 Vite 开发代理读取认证配置时未优先使用环境变量的问题。

### 安全
- BasicAuth 在缺少配置文件且未设置密码时改为生成随机密码，避免继续使用固定默认密码。
- 对多处 API 查询参数增加类型转换和上限钳制，降低异常输入导致的资源消耗风险。

## [1.6.4] - 2026-06-26

### 新增
- 支持通过环境变量配置数据库连接（DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME）
- Docker Compose 内置 MySQL 8，开箱即用
- 添加 `.env.example` 配置示例文件

### 改进
- 优化 Docker 部署文档，支持一键启动

## [1.6.3] - 2026-06-25

### 修复
- 修复历史明细选项卡首次进入时数据闪烁问题：移除 `initialRuns` 初始数据，改为加载时显示 loading 状态

## [1.6.2] - 2026-06-23

### 修复
- 修复 `scanner_integration/__init__.py` 第430行和第868行注释与代码粘连导致的逻辑错误
- 修复 `web/routes/health.py` 中引用不存在的 `_bridge` 变量，改为正确的 `bridge`
- 修复 `scanner_integration/persistence.py`、`web/routes/history.py`、`web/routes/scan.py`、`web/routes/subscribe.py` 中SQL占位符从SQLite风格 `?` 改为MySQL兼容的 `%s`
- 实现 `scanner_integration/video_check.py` 中缺失的 `health_check_persistent` 函数
- 修复 `scanner_integration/__init__.py` 中引用不存在的 `_db.DB_PATH` 属性，适配MySQL架构

### 改进
- 重构 `scanner_integration/__init__.py` 中重复的去重代码，提取 `_deduplicate_and_normalize()` 辅助函数
- 优化 `Dockerfile` 使用多阶段构建，减小镜像体积
- 将 `Dockerfile` 中的Flask内置服务器替换为gunicorn生产服务器
- 修复 `docker-compose.yml` 中已弃用的 `version` 字段
- 修复 `.gitignore` 中重复的 `basic_auth.json` 条目
- 优化 `frontend/vite.config.js` 添加try-catch处理配置文件缺失情况
- 清理 `tests/` 目录中的测试报告JSON和截图文件
- 创建 `.dockerignore` 文件优化Docker构建
- 在 `requirements.txt` 中添加 `gunicorn>=21.2.0` 依赖

### 安全
- 将 `database/db_config.json` 添加到 `.gitignore` 忽略列表

### 运维
- 更新 `docker-compose.yml` 添加 `db_config.json` volume 挂载，支持MySQL数据库配置
- 更新 README.md 版本号至 v1.6.2

## [1.6.1] - 2026-06-21

### 修复
- 修复 `scanner_integration/__init__.py` 文件编码损坏问题（109 个 U+FFFD 替换字符）
- 修复 30+ 个 docstring 缺失第三个闭合引号导致的 SyntaxError
- 修复 12 个字符串缺失闭合引号的问题
- 修复多处注释与代码同行导致的缩进错误
- 修复 `database/db.py` 中旧数据库升级时 `deleted_at` 列不存在导致 `CREATE INDEX` 失败的问题
- 添加 `_table_exists()` 辅助函数，将列补齐逻辑移到 `executescript()` 之前执行

## [1.6.0] - 2026-06-21

### 新增
- 键盘快捷键支持：Ctrl+S保存、Ctrl+F搜索、Alt+1-8切换Tab
- 无障碍访问(a11y)支持：语义化标签、ARIA属性、焦点管理
- 前端公共组件：LogPanel日志面板、useClipboard剪贴板、平台/质量/日期工具函数
- 健康检查增强：FFmpeg/磁盘/内存/扫描模块检查，版本和运行时间信息
- 表单即时验证反馈
- 操作确认弹窗（终止测试、停止扫描、强制清除、清空日志）

### 改进
- API响应格式统一为 `{'ok': True/False, 'data': ...}` 格式
- 全局错误处理器：404/500/405返回JSON而非HTML
- 分页参数添加上限校验（最大200条）
- 前端轮询优化：移除TestingTab双重轮询，添加指数退避和Tab可见性感知
- 数据库索引优化：添加复合索引、唯一约束、scan_logs.level字段

### 修复
- 修复API端点缺少HTTP方法限制的问题
- 修复ScannerTab triggerPending吞掉错误的问题

## [1.5.0] - 2026-06-21

### 新增
- 集成 Quake/Hunter/DayDayMap 扫描模块，自动发现酒店 IPTV 服务器
- 支持 ZHGXTV、JSMpeg、Tvheadend、IPTV互动等多种 IPTV 系统扫描
- C 段扫描：对已发现的 IP 所在 /24 子网进行扩展扫描
- 省份/城市/运营商过滤功能
- 健康检查：定时检测已发现频道的可用性，自动移除失效频道
- DuckDuckGo 扫描支持（可选）
- Fofa 平台扫描支持

### 改进
- 扫描结果可选择性送入测速流水线
- 自动频道名归一和分类（央视频道、卫视频道、各省频道）
- 快速过滤（HEAD 请求验证）+ 深度检测（带宽/延迟/稳定性/分辨率）

## [1.4.0] - 2026-06-20

### 新增
- SQLite 数据库存储，替代原有 JSON 文件存储
- 数据库自动迁移：首次启动自动迁移 config.json 和 history.json
- 测速历史、详情、日志和实时进度保存在 SQLite 中
- 扫描历史和结果持久化存储

### 改进
- 数据库最多保留最近 50 轮历史记录
- 日志保留策略：测速日志 30 天、扫描日志 7 天、持久化结果 90 天
- 支持通过环境变量 `IPTV_DB_PATH` 自定义数据库路径

## [1.3.0] - 2026-06-19

### 新增
- Flask Web 后台，提供完整的 API 接口
- Vue 3 + TDesign 前端界面
- 支持深色/浅色主题切换
- 总览、历史明细、系统测试、系统配置、频道扫描、扫描配置、检测监控、扫描结果等标签页
- BasicAuth 认证保护
- Vite 开发模式，支持前端热更新

### 改进
- 重构目录结构，分离前后端代码
- 支持 Docker 部署（Dockerfile + docker-compose.yml）
- 支持 Gunicorn 生产部署

## [1.2.0] - 2026-06-18

### 新增
- FFmpeg 分辨率检测和编码信息获取
- 带宽测速：结合下载采样计算带宽
- 支持 H.265/HEVC 编码带宽折算
- 频道别名归一系统（精确匹配 + 正则匹配）
- 模板化输出：按频道模板只测试需要的频道

### 改进
- 实时写入输出文件（TXT 和 M3U 格式）
- 支持最低分辨率、最低带宽筛选
- 单频道输出数量限制

## [1.1.0] - 2026-06-17

### 新增
- 多 M3U 订阅源聚合解析
- 频道模板系统，支持分类和频道名
- 别名映射，支持精确别名和正则别名
- 运行模式：once、times、interval
- 测速结果输出到 TXT 和 M3U 文件

### 改进
- 优化测速并发控制
- 支持系统带宽和内存限制

## [1.0.0] - 2026-06-16

### 新增
- 基础测速功能
- 命令行运行模式
- 配置文件支持（config.json、subscribe.txt、alias.txt、demo.txt）
- 测速历史记录（output/history.json）

### 说明
- 初始版本，实现核心测速引擎
- 支持基本的频道匹配和测速逻辑

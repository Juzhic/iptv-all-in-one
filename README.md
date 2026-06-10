# IPTV 频道质量筛选工具

从多个 M3U 订阅源中筛选可用且质量较高的 IPTV 频道，支持 FFmpeg 分辨率检测、带宽测速、频道别名归一、模板化输出、Web 后台配置、历史记录和定时运行。

集成 IPTV 频道扫描模块，可通过搜索引擎 API（Quake/Hunter/DayDayMap）自动发现酒店 IPTV 服务器，提取频道列表并送入测速流水线。

## 当前版本说明

本项目当前以 SQLite 作为主要数据存储，默认数据库文件为 `iptv.db`。

旧版 README 中提到的 `config.json`、`subscribe.txt`、`alias.txt`、`demo.txt` 已不再作为日常配置入口。现在请通过 Web 后台的"系统配置"页面维护：

| 数据 | 当前存储位置 | 说明 |
| --- | --- | --- |
| 系统参数 | `iptv.db` 的 `config_data` 表，key 为 `config` | 测速时长、并发数、分辨率阈值、运行模式等 |
| 订阅源 | `config_data` 表，key 为 `subscribe` | 每行一个 M3U 地址 |
| 频道模板 | `config_data` 表，key 为 `demo` | 决定要匹配、测速和输出哪些频道 |
| 别名映射 | `config_data` 表，key 为 `alias` | 将不同频道名归一到模板中的主名 |
| 扫描配置 | `config_data` 表，key 为 `scan_config` | 扫描模块的 API Key、平台、省份等配置 |
| 测速历史 | `runs`、`run_results` | 最近运行结果和每个频道 URL 的测速详情 |
| 扫描历史 | `scan_runs`、`scan_results` | 扫描任务记录和扫描到的频道数据 |
| 运行日志 | `run_logs` | 每轮任务日志 |
| 运行进度 | `run_progress` | Web 页面实时进度 |
| 扫描进度 | `scan_progress` | 扫描实时进度 |

如果根目录存在旧的 `config.json`，程序首次启动且数据库里没有系统配置时，会尝试迁移到 SQLite，并把原文件重命名为 `config.json.bak`。旧的 `output/history.json` 也会迁移到 SQLite，并重命名为 `.bak`。

## 功能

### 测速模块

- 聚合多个 M3U 订阅源并解析频道地址。
- 按频道模板只测试需要的频道，避免全量盲测。
- 支持精确别名和 `re:` 正则别名，统一不同源里的频道名称。
- 使用 FFmpeg 检测分辨率、编码信息，并结合下载采样计算带宽。
- 支持最低分辨率、最低带宽、H.265 带宽折算、单频道输出数量限制。
- 测速通过后实时写入 `output/result.txt` 和 `output/result.m3u`。
- Web 后台支持配置编辑、手动触发、进度查看、历史查看、日志查看、结果下载。
- 支持 `once`、`times`、`interval` 三种运行模式。

### 扫描模块（新增）

- 通过搜索引擎 API（Quake 360、Hunter 鹰图、DayDayMap）自动发现酒店 IPTV 服务器。
- 支持 ZHGXTV、JSMpeg 等多种 IPTV 系统的频道提取。
- C 段扫描：对已发现的 IP 所在 /24 子网进行扩展扫描。
- 快速过滤（HEAD 请求验证）+ 深度检测（带宽/延迟/稳定性/分辨率）。
- 自动频道名归一和分类（央视频道、卫视频道、各省频道）。
- 省份/城市/运营商过滤。
- 健康检查：定时检测已发现频道的可用性，自动移除失效频道。
- 扫描结果可选择性送入测速流水线，经 FFmpeg 深度检测后输出。

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

系统还需要安装 FFmpeg，并确保 `ffmpeg` 在 `PATH` 中。也可以通过环境变量 `FFMPEG_BIN` 指定可执行文件路径。

前端使用 Vue 3 + TDesign 组件库，需要 Node.js 18+ 环境。首次使用或前端代码有变动时需重新构建：

```bash
cd frontend
npm install    # 首次安装依赖
npm run build  # 构建前端，输出到 dist/
cd ..
```

### 2. 启动 Web 后台

```bash
python web.py
```

默认访问地址：

```text
http://localhost:58080
```

**开发模式**（前端修改自动热更新，无需手动构建）：

```bash
python web.py --dev
```

此模式下 Vite 开发服务器启动在 `http://localhost:3000`，API 请求自动代理到 Flask 后端 `:58080`。修改 Vue 源码后浏览器即时刷新，无需手动 `npm run build`。

BasicAuth protects the Web backend and APIs by default. Credentials are read
from `basic_auth.json` in the program directory:

```json
{
  "username": "admin",
  "password": "admin",
  "realm": "IPTV Test"
}
```

If the file is missing or invalid, the fallback account is `admin` / `admin`.
Result subscription downloads stay public: `/api/download/txt` and
`/api/download/m3u`.

开发模式下，Vite 代理也会自动读取同一份 `basic_auth.json` 并转发 BasicAuth 头，因此 `http://localhost:3000` 下的总览、历史、扫描等 API 页面可直接调试。

Web 服务固定使用 `58080` 端口。如果端口已被旧进程占用，启动会失败并提示先结束占用进程。

启动后进入"系统配置"页，依次填写或调整：

1. 订阅源：每行一个 M3U 地址。
2. 频道模板：需要输出的频道和分类。
3. 别名映射：把源里的不同频道名映射为模板主名。
4. 参数配置：分辨率、带宽、并发数、运行模式等。

保存后可以在页面中手动触发一次测速。

### 3. 使用扫描模块

进入"频道扫描"标签页：

1. 配置 API Key（Quake/Hunter/DayDayMap 至少一个）。
2. 选择要扫描的省份（可多选，留空表示全国）。
3. 点击"开始扫描"。
4. 扫描完成后，切换到"扫描结果"标签页查看频道列表。
5. 勾选需要的频道，点击"送入选中去测速"，频道将进入测速流水线。

### 4. 命令行运行

也可以直接运行核心任务：

```bash
python test_engine.py
```

命令行同样会从 `iptv.db` 读取配置，不再读取 `subscribe.txt`、`alias.txt`、`demo.txt`。

## 系统参数

默认参数定义在 `test_engine.py` 的 `DEFAULT_CONFIG` 中，保存后会写入数据库。

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `test_duration` | `15` | 单个频道地址测速时长，单位秒 |
| `max_workers` | `30` | 最大并发测试线程数 |
| `system_bandwidth_limit_MBps` | `50` | 系统下行带宽限制，超过后暂停启动新测试；`0` 表示关闭 |
| `min_bandwidth_MBps` | `1.0` | 频道最低带宽要求，单位 MB/s |
| `bandwidth_compensation_MBps` | `2.0` | 未获取到分辨率时的带宽补偿阈值 |
| `h265_bandwidth_ratio` | `0.6` | H.265/HEVC 编码带宽阈值折算比例 |
| `max_urls_per_channel` | `10` | 每个频道最多输出地址数；`0` 表示不限制 |
| `show_update_time` | `true` | 是否在输出结果中加入更新时间 |
| `update_time_position` | `top` | 更新时间位置，支持 `top` 或 `bottom` |
| `min_width` | `1920` | 最低分辨率宽度 |
| `min_height` | `1080` | 最低分辨率高度 |
| `output_txt` | `output/result.txt` | TXT 输出路径 |
| `output_m3u` | `output/result.m3u` | M3U 输出路径 |
| `run_mode` | `once` | 运行模式：`once`、`times`、`interval` |
| `run_times` | `[]` | `times` 模式下的执行时间列表，例如 `06:00,12:00,18:00` |
| `run_interval_minutes` | `60` | `interval` 模式下的执行间隔，单位分钟 |

## 文本配置格式

这些内容现在都在 Web 后台编辑，保存后写入 `iptv.db`。

### 订阅源

每行一个 M3U 地址，空行和 `#` 开头的注释行会被忽略。

```text
https://example.com/playlist1.m3u
https://example.com/playlist2.m3u
```

### 别名映射

每行一个主名映射，第一列是主名，后续列是别名。以 `re:` 开头的别名会按正则表达式匹配。

```text
CCTV-1,re:(?i)^\s*CCTV[-\s_]*0?1(?![0-9Kk+])[\s\S]*$,CCTV1,CCTV-01,CCTV-1综合
CCTV-5+,re:(?i)^\s*CCTV[-\s_]*0?5\s*(?:\+|PLUS)[\s\S]*$,CCTV5+,CCTV-5+体育赛事
```

模板中的频道名建议使用主名。源里的频道名命中别名后，会统一归一到主名参与匹配和输出。

### 频道模板

包含 `,#genre#` 的行是分类标题，其他行是频道主名。只有模板中出现的频道才会被匹配、测速和输出。

```text
央视频道,#genre#
CCTV-1
CCTV-5
CCTV-5+

卫视频道,#genre#
广东卫视
浙江卫视
湖南卫视
```

频道模板为空时不会执行有效测速。

## 输出结果

每轮任务会把通过筛选的地址写入：

```text
output/result.txt
output/result.m3u
```

Web 后台的下载接口会根据数据库中最近一轮通过的结果动态生成文件：

```text
/api/download/txt
/api/download/m3u
```

测速历史、详情、日志和实时进度保存在 SQLite 中，不再依赖 `output/history.json`。当前数据库最多保留最近 50 轮历史记录。

## 运行模式

### `once`

只手动触发或命令行运行一次。Web 服务启动时不会自动开始测速。

### `times`

按照指定时间点循环运行，例如：

```json
{
  "run_mode": "times",
  "run_times": ["06:00", "12:00", "18:00"]
}
```

### `interval`

按间隔循环运行，例如：

```json
{
  "run_mode": "interval",
  "run_interval_minutes": 120
}
```

## 项目结构

```text
IPTV-Test/
├── web.py                      # Flask Web 后台和 API
├── test_engine.py              # 核心测速引擎：频道匹配、M3U 源解析、测速编排、输出生成
├── db.py                       # SQLite 表结构、配置、历史、日志和进度存取
├── alias.py                    # 共享别名模块（测速和扫描共用）
├── FFmpegTest.py               # FFmpeg 分析、带宽采样和 HTTP 拉流检测
├── scanner_integration/        # 扫描模块
│   ├── __init__.py             # 异步桥接、扫描编排、定时任务入口
│   ├── config_bridge.py        # 扫描配置读写
│   ├── key_manager.py          # API Key 管理（Quake/Hunter/DayDayMap）
│   ├── platforms.py            # 平台扫描（Quake/Hunter/DayDayMap/ZHGXTV/JSMpeg/Tvheadend/DDGS）
│   ├── video_check.py          # 流验证：快速过滤、深度检测、健康检查
│   ├── channel_utils.py        # 频道名归一、分类
│   ├── network.py              # 异步 HTTP 会话、全局信号量
│   ├── geo_data.py             # 地理数据、省份检测
│   ├── province_cities.py      # 省市频道映射
│   ├── domain_ip_scanner.py    # DNS/Censys/RapidDNS 域名扫描
│   ├── logger_bridge.py        # 日志模块
│   └── pca-code.json           # 行政区划数据
├── frontend/                   # Vue 3 前端源码（TDesign Vue Next）
│   ├── index.html              # SPA 入口
│   ├── package.json            # 前端依赖和构建脚本
│   ├── vite.config.js          # Vite 构建配置（含开发代理）
│   ├── node_modules/           # npm 依赖（gitignore）
│   └── src/
│       ├── main.js             # Vue 应用初始化
│       ├── api.js              # 统一 API 请求封装
│       ├── App.vue             # 根组件：布局、头部、标签页
│       ├── components/
│       │   ├── OverviewTab.vue # 总览：统计卡片、SVG 趋势图、运行摘要
│       │   ├── HistoryTab.vue  # 历史：日期筛选、表格、详情展开、日志弹窗
│       │   ├── ChannelsTab.vue # 按频道：搜索过滤、可折叠卡片
│       │   ├── TestingTab.vue  # 系统测试：控制、进度、日志、下载链接
│       │   ├── SettingsTab.vue # 配置：文本编辑器、参数表单
│       │   ├── ScannerTab.vue  # 频道扫描：控制、进度、日志
│       │   ├── ScanConfigTab.vue # 扫描配置：API Key 管理、定时设置
│       │   └── ScanResultsTab.vue # 扫描结果：分页表格、筛选、导出
│       └── composables/
│           ├── useTheme.js     # 深色/浅色主题切换
│           └── usePolling.js   # 轮询定时器
├── dist/                       # 前端构建产物（gitignore，需 npm run build）
├── requirements.txt            # Python 依赖
├── basic_auth.json             # Web 后台 BasicAuth 配置
├── iptv.db                     # SQLite 数据库，运行后生成或更新
└── output/                     # TXT/M3U 输出目录，运行后生成
```

## Web 标签页说明

前端使用 [TDesign Vue Next](https://tdesign.tencent.com/vue-next/overview) 组件库构建，支持深色/浅色主题切换。

| 标签 | 说明 |
| --- | --- |
| 总览 | 通过率趋势图、统计卡片、运行摘要和值得关注 |
| 历史明细 | 测速历史列表，日期筛选，展开查看详细结果和日志 |
| 按频道 | 按频道名查看所有测速结果，支持搜索和过滤 |
| 系统测试 | 触发/停止测速、实时进度和日志、TXT/M3U 下载和预览 |
| 系统配置 | 编辑订阅源、频道模板、别名映射，调整系统参数 |
| 📡 频道扫描 | 触发/停止扫描、健康检查、实时进度和日志 |
| ⚙️ 扫描配置 | API Key 管理、扫描参数、定时扫描设置 |
| 📋 扫描结果 | 查看扫描频道列表、按分类/省份过滤、送入测速、导出 M3U |

## 扫描模块参数

在"频道扫描"标签页的配置区域可设置以下参数：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `quake_api_key` | `""` | Quake 360 API Key |
| `hunter_api_key` | `""` | Hunter 鹰图 API Key |
| `daydaymap_api_key` | `""` | DayDayMap API Key |
| `enabled_platforms` | `[]` | 启用的扫描平台列表 |
| `selected_provinces` | `[]` | 扫描省份过滤（多选，空表示全国） |
| `operator` | `""` | 运营商过滤（电信/联通/移动/广电） |
| `quake_size` | `200` | 每个平台每次扫描返回的最大条数 |
| `enable_c_scan` | `true` | 是否开启 C 段扩展扫描 |
| `daily_full_update` | `true` | 每天扫描（关闭后按 `update_days` 选择星期几） |
| `update_time` | `"03:00"` | 定时扫描时间 |
| `update_days` | `[0,1,2,3,4,5,6]` | 定时扫描的星期几（0=周一, 6=周日） |
| `deep_concurrent` | `15` | 深度检测并发数 |
| `auto_refill` | `true` | 频道数量不足时自动补充扫描 |

## 别名系统

测速模块和扫描模块共享同一套别名系统（`alias.py`）。别名数据存储在数据库 `config_data` 表（key=`alias`）中。

别名格式：每行一个主名映射，第一列是主名，后续列是别名。以 `re:` 开头的别名会按正则表达式匹配。匹配引擎使用字典 O(1) 精确查找 + 预编译正则兜底，支持 4 万+ 条别名高效匹配。

## 常见问题

**Q: 修改配置后没有生效？**
请确认是在 Web 后台保存到数据库。旧的 `subscribe.txt`、`alias.txt`、`demo.txt` 不再被读取。每轮测速开始时会重新读取数据库配置。

**Q: FFmpeg 未找到？**
安装 FFmpeg 并确保命令行可直接执行 `ffmpeg`。如果不在 `PATH` 中，设置 `FFMPEG_BIN` 指向可执行文件。

**Q: 所有频道都不通过？**
在 Web 后台降低 `min_bandwidth_MBps`、`min_width`、`min_height`，或检查频道模板和别名是否能匹配订阅源里的实际频道名。

**Q: 并发太高导致机器或网络压力大？**
降低 `max_workers`，必要时设置 `system_bandwidth_limit_MBps`。

**Q: 想清空历史或配置？**
历史数据在 `iptv.db` 中。删除数据库会同时清空配置、历史、日志和进度；删除前请先备份。

**Q: 扫描模块报错 aiohttp 未安装？**
运行 `pip install aiohttp>=3.9.0` 安装扫描模块依赖。扫描模块为可选功能，不安装 aiohttp 不影响测速模块的正常使用。

**Q: 扫描需要 API Key 吗？**
是的。至少需要配置一个搜索引擎的 API Key（Quake 360、Hunter 鹰图或 DayDayMap 之一）。在"频道扫描"标签页的配置区域填写，点击旁边的"获取 ↗"链接可跳转到对应平台申请。

**Q: 如何设置定时扫描？**
在"频道扫描"标签页的配置区域底部，勾选要扫描的星期几（或勾选"每天"），设置扫描时间，保存配置即可。页面会显示下次扫描的倒计时。定时扫描在后台自动执行，无需手动触发。

**Q: 首次部署或更新后页面空白/报错？**
需要先构建前端：`cd frontend && npm install && npm run build`。构建完成后 `dist/` 目录会生成 SPA 文件，Flask 启动时自动服务。

**Q: 前端开发调试？**
运行 `python web.py --dev`，会自动启动 Vite 开发服务器（`:3000`）+ Flask API 服务器（`:58080`）。修改 Vue 源码后浏览器自动热更新，无需手动构建。

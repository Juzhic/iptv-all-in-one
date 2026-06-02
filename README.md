# IPTV 频道质量筛选工具

从多个 M3U 订阅源中筛选可用且质量较高的 IPTV 频道，支持 FFmpeg 分辨率检测、带宽测速、频道别名归一、模板化输出、Web 后台配置、历史记录和定时运行。

## 当前版本说明

本项目当前以 SQLite 作为主要数据存储，默认数据库文件为 `iptv.db`。

旧版 README 中提到的 `config.json`、`subscribe.txt`、`alias.txt`、`demo.txt` 已不再作为日常配置入口。现在请通过 Web 后台的“系统配置”页面维护：

| 数据 | 当前存储位置 | 说明 |
| --- | --- | --- |
| 系统参数 | `iptv.db` 的 `config_data` 表，key 为 `config` | 测速时长、并发数、分辨率阈值、运行模式等 |
| 订阅源 | `config_data` 表，key 为 `subscribe` | 每行一个 M3U 地址 |
| 频道模板 | `config_data` 表，key 为 `demo` | 决定要匹配、测速和输出哪些频道 |
| 别名映射 | `config_data` 表，key 为 `alias` | 将不同频道名归一到模板中的主名 |
| 测速历史 | `runs`、`run_results` | 最近运行结果和每个频道 URL 的测速详情 |
| 运行日志 | `run_logs` | 每轮任务日志 |
| 运行进度 | `run_progress` | Web 页面实时进度 |

如果根目录存在旧的 `config.json`，程序首次启动且数据库里没有系统配置时，会尝试迁移到 SQLite，并把原文件重命名为 `config.json.bak`。旧的 `output/history.json` 也会迁移到 SQLite，并重命名为 `.bak`。

## 功能

- 聚合多个 M3U 订阅源并解析频道地址。
- 按频道模板只测试需要的频道，避免全量盲测。
- 支持精确别名和 `re:` 正则别名，统一不同源里的频道名称。
- 使用 FFmpeg 检测分辨率、编码信息，并结合下载采样计算带宽。
- 支持最低分辨率、最低带宽、H.265 带宽折算、单频道输出数量限制。
- 测速通过后实时写入 `output/result.txt` 和 `output/result.m3u`。
- Web 后台支持配置编辑、手动触发、进度查看、历史查看、日志查看、结果下载。
- 支持 `once`、`times`、`interval` 三种运行模式。

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

系统还需要安装 FFmpeg，并确保 `ffmpeg` 在 `PATH` 中。也可以通过环境变量 `FFMPEG_BIN` 指定可执行文件路径。

### 2. 启动 Web 后台

```bash
python web.py
```

默认访问地址：

```text
http://localhost:58080
```

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

Web 服务固定使用 `58080` 端口。如果端口已被旧进程占用，启动会失败并提示先结束占用进程。

启动后进入“系统配置”页，依次填写或调整：

1. 订阅源：每行一个 M3U 地址。
2. 频道模板：需要输出的频道和分类。
3. 别名映射：把源里的不同频道名映射为模板主名。
4. 参数配置：分辨率、带宽、并发数、运行模式等。

保存后可以在页面中手动触发一次测速。

### 3. 命令行运行

也可以直接运行核心任务：

```bash
python app.py
```

命令行同样会从 `iptv.db` 读取配置，不再读取 `subscribe.txt`、`alias.txt`、`demo.txt`。

## 系统参数

默认参数定义在 `app.py` 的 `DEFAULT_CONFIG` 中，保存后会写入数据库。

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
├── app.py              # 核心测速、匹配、输出和命令行入口
├── web.py              # Flask Web 后台和 API
├── db.py               # SQLite 表结构、配置、历史、日志和进度存取
├── FFmpegTest.py       # FFmpeg 分析、带宽采样和 HTTP 拉流检测
├── templates/
│   └── index.html      # Web 后台页面
├── requirements.txt    # Python 依赖
├── iptv.db             # SQLite 数据库，运行后生成或更新
└── output/             # TXT/M3U 输出目录，运行后生成
```

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

# AGENTS.md — AI 项目上下文指南

## 项目概述

IPTV 频道质量筛选工具。从多个 M3U 订阅源中筛选高质量频道（1080P + 高带宽），支持频道别名识别、模板化输出、实时写入、定时执行，以及 Web 管理后台。

---

## 项目结构

```
IPTV-Test/
├── app.py              # 核心逻辑 + 命令行入口（含定时调度）
├── web.py              # Web 管理后台（Flask，API + 仪表盘 + 配置管理）
├── db.py               # SQLite 数据库模块（所有数据持久化）
├── FFmpegTest.py       # FFmpeg 分辨率探测 + 带宽测速（被 app.py 调用）
├── templates/
│   └── index.html      # Web 前端单页面（仪表盘 + 配置管理）
├── config.json         # 所有可配置项
├── subscribe.txt       # M3U 订阅源地址（每行一个）
├── alias.txt           # 频道别名映射（主名 + 精确别名 + re:正则别名）
├── demo.txt            # 目标频道模板（分类标题 + 频道名，决定输出内容）
├── iptv.db             # SQLite 数据库（运行时自动生成，已 gitignore）
├── requirements.txt    # Python 依赖：requests, psutil, flask
├── output/             # 运行时输出目录（已 gitignore）
│   ├── result.txt      # TXT 格式输出（实时写入，供播放器使用）
│   └── result.m3u      # M3U 格式输出（实时写入，供播放器使用）
└── logs/               # 日志目录（运行时生成，已 gitignore）
```

---

## 核心数据流

```
subscribe.txt（M3U源地址）
    ↓ fetch_m3u_playlist()
M3U 内容
    ↓ parse_iptv_addresses()
[(频道名, URL), ...]
    ↓ match_channels_from_m3u() + alias.txt 别名解析
只保留 demo.txt 中有的频道
    ↓ filter_and_save_playlist() + FFmpegTest 测速
通过测速的频道
    ├─→ on_pass_callback → 实时写入 result.txt / result.m3u（供播放器）
    └─→ save_run_result() → insert_run() → iptv.db（供 Web 仪表盘）
```

---

## 数据库（db.py）

SQLite 数据库文件：`iptv.db`（项目根目录）

### 表结构

**runs** — 测试轮次
```sql
id, run_id (UNIQUE), started_at, finished_at, duration_seconds,
total_tested, total_passed, total_failed, pass_rate,
unique_channels_passed, unique_channels_total
```

**run_results** — 每条测试结果
```sql
id, run_id (FK→runs), channel, url, resolution,
bandwidth_MBps, codec, is_h265, sample_seconds,
passed, reason, cost_seconds
```

索引：`idx_results_run_id`, `idx_results_channel`
外键：`run_results.run_id → runs.run_id ON DELETE CASCADE`
自动清理：超过 50 轮自动删除最旧记录

### 主要函数

| 函数 | 用途 |
|------|------|
| `init_db()` | 创建表结构（幂等，首次启动调用） |
| `insert_run(run_data)` | 写入一轮完整结果（app.py 调用） |
| `get_latest_run()` | 获取最近一轮（含所有结果，Web 仪表盘用） |
| `get_latest_passed_results()` | 获取最近一轮通过的频道（生成下载文件） |
| `get_run_history()` | 历史轮次列表（不含详细结果） |
| `get_run_detail(run_id)` | 指定轮次详情 |
| `get_channel_summary(run_id)` | 按频道聚合结果 |
| `get_codec_stats(run_id)` | 编码格式统计 |
| `delete_run(run_id)` | 删除指定轮次 |
| `migrate_from_json()` | 首次启动自动迁移 history.json → SQLite |

---

## 各文件职责详解

### app.py

- **配置加载**：`load_config('config.json')` → 返回配置字典，缺失项用默认值
- **别名系统**：`load_aliases()` → 返回 3 元组 `(canonical_to_aliases, name_to_canonical, regex_aliases)`
  - `name_to_canonical`：精确匹配字典（O(1)）
  - `regex_aliases`：预编译正则列表 `[(re.Pattern, 主名), ...]`
  - `match_channel_name(name, name_to_canonical, regex_aliases)` 先精确后正则
- **模板解析**：`parse_demo_file()` → `[(genre, [频道名, ...]), ...]`
- **频道匹配**：`match_channels_from_m3u()` → `{主名: [url1, url2, ...]}`
- **测速筛选**：`filter_and_save_playlist()` → 多线程并发测试，支持 `on_pass_callback` 实时回调
- **输出**：`save_result_txt()` / `save_result_m3u()` → 实时写入文件（供播放器使用）
- **持久化**：`save_run_result()` → `db.insert_run()` 写入 SQLite
- **定时调度**：`_next_run_datetime()` + `__main__` 循环，绝对时间触发，无漂移
- **带宽限速**：`SystemDownloadLimiter` → 用 `psutil` 采样系统总下行，超过阈值暂停新测试

### web.py

Flask Web 管理后台，提供仪表盘和配置管理界面。

**API 路由：**

| 路由 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 渲染主页（仪表盘 + 配置管理） |
| `/api/config` | GET | 读取 config.json（合并默认值） |
| `/api/config` | POST | 保存 config.json（校验合法 key） |
| `/api/text/<filename>` | GET | 读取文本文件（alias/demo/subscribe.txt） |
| `/api/text/<filename>` | POST | 保存文本文件（白名单校验） |
| `/api/runs` | GET | 测试历史列表 |
| `/api/run/<run_id>` | GET | 单轮详情 |
| `/api/run/<run_id>` | DELETE | 删除某轮记录 |
| `/api/download/<fmt>` | GET | 下载 result.txt/m3u（从数据库动态生成） |
| `/api/trigger` | POST | 触发一次测试运行（后台线程） |
| `/api/status` | GET | 获取当前测试运行状态 |

**文本文件白名单**：`alias.txt`, `demo.txt`, `subscribe.txt`

### db.py

所有 SQLite 操作封装。每个线程独立连接（`threading.local`），WAL 模式，外键开启。详见上方数据库章节。

### FFmpegTest.py

- `ffmpeg_test(url)`：调 FFmpeg 探测分辨率（subprocess，5 秒超时）
- `analyze_iptv_with_ffmpeg(url, duration)`：完整测速入口（探测 + 带宽）
- `test_direct_bandwidth(url, width, height, duration)`：直链带宽测试
  - chunk_size=128KB，从收到第一个数据块后开始计时（排除连接建立耗时）
- `test_hls_bandwidth(url, width, height, duration)`：HLS 分片带宽测试
  - chunk_size=128KB，用实际下载时间（`download_seconds`）计算带宽，不用 #EXTINF 声明时长
- `probe_hls_url(url, deadline)`：探测无后缀地址是否实际返回 HLS 播放列表
- `pick_hls_variant()` / `parse_hls_segments()`：HLS 播放列表解析
- `_timed_out_urls`：超时 URL 注册表，流读取循环中检测并主动退出
- `register_timeout(url)` / `clear_timeouts()`：超时标记管理

---

## 配置体系

所有配置集中在 `config.json`，通过 `load_config()` 读取。配置项缺失时自动使用 `DEFAULT_CONFIG` 中的默认值。**Web 后台的「系统配置」Tab 可直接编辑**，无需手动改文件。

**运行模式**（`run_mode`）：
- `once`：运行一次退出
- `times`：按 `run_times` 列表指定的时间循环执行，支持跨天
- `interval`：每轮结束后等待 `run_interval_minutes` 分钟再执行，从结束时刻开始计，无漂移

**筛选阈值全部走 config**，不在代码里硬编码：
- `min_width` / `min_height`：最低分辨率
- `min_bandwidth_MBps`：最低带宽
- `bandwidth_compensation_MBps`：未获取分辨率时的补偿阈值
- `h265_bandwidth_ratio`：H.265 编码的带宽阈值比例
- `system_bandwidth_limit_MBps`：系统总下行限速

---

## 关键设计决策

1. **别名正则预编译**：`load_aliases` 在启动时一次性编译所有 `re:` 别名，运行时用预编译对象匹配
2. **实时写入**：每个频道通过测速后立即触发 `on_pass_callback`，用 `threading.Lock` 保护文件写入
3. **连接泄漏修复**：超时时调用 `register_timeout(url)`，FFmpegTest 流读取循环每读一个 chunk 检查 `_is_timed_out()`，命中立即 break，触发连接关闭
4. **executor 不阻塞**：`executor.shutdown(wait=False, cancel_futures=True)`，主循环通过 `channel_timeout` 已收集所有结果，不等残留线程退出
5. **带宽测速精度**：
   - chunk_size=128KB（减少 Python 循环开销）
   - 直链测速从收到第一个 chunk 后计时（排除连接建立耗时）
   - HLS 测速用实际下载时间（`download_seconds`）而非 #EXTINF 声明时长
6. **带宽单位**：`SystemDownloadLimiter` 使用 MB/s（兆字节/秒），config 里注明
7. **绝对时间调度**：每次计算 `next_run = now + interval`，避免时间漂移
8. **SQLite WAL 模式**：支持 Web 读 + app 写并发，不会互相阻塞

---

## 常见修改场景

### 调整筛选标准

编辑 `config.json`（或通过 Web 后台「系统配置」Tab），不动代码。

### 添加新频道别名

在 `alias.txt` 中按格式添加行：`主名,别名1,re:正则,...`（或通过 Web 后台编辑）

### 更换输出的 EPG 地址

修改 `app.py` 中 `save_result_m3u()` 函数里的 `#EXTM3U x-tvg-url="..."`，以及 `web.py` 中 `_generate_result_m3u()` 的对应位置。

### 添加新的配置项

1. 在 `config.json` 中添加 key（同时加 `# key` 注释行）
2. 在 `app.py` 的 `DEFAULT_CONFIG` 字典中添加默认值
3. 在 `web.py` 的 `api_save_config` 中将 key 加入 `valid_keys`
4. 在 `templates/index.html` 的配置表单中添加对应输入框

---

## 编码规范

- 所有配置走 `config.json`，不在代码里硬编码魔法数字
- 频道名匹配统一走 `match_channel_name()`，不自行判断
- HTTP 请求统一走 `FFmpegTest.http_get()`，不直接用 `requests.get()`
- 数据库操作统一走 `db.py`，不直接写 SQL
- 文件路径统一用配置项，不硬编码文件名
- 中文注释和日志，面向国内用户

---

## 运行方式

```bash
# 安装依赖
pip install -r requirements.txt

# 单次测速
python app.py

# 定时运行：修改 config.json 的 run_mode 后运行，Ctrl+C 退出
python app.py

# 启动 Web 管理后台
python web.py
# 浏览器访问 http://localhost:5000
```

首次启动时自动迁移 `output/history.json` 到 `iptv.db`（迁移后原文件重命名为 `.bak`）。

Windows 环境下使用 PyCharm，虚拟环境建议建在项目目录下 `.venv`，解释器指向 `.venv/Scripts/python.exe`。

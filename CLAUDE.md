# CLAUDE.md — AI 项目上下文指南

## 项目概述

IPTV 频道质量筛选工具。从多个 M3U 订阅源中筛选高质量频道（1080P + 高带宽），支持频道别名识别、模板化输出、实时写入和定时执行。

---

## 项目结构

```
IPTV-Test/
├── app.py              # 核心逻辑 + 命令行入口（含定时调度）
├── FFmpegTest.py       # FFmpeg 分辨率探测 + 带宽测速（被 app.py 调用）
├── config.json         # 所有可配置项
├── subscribe.txt       # M3U 订阅源地址（每行一个）
├── alias.txt           # 频道别名映射（主名 + 精确别名 + re:正则别名）
├── demo.txt            # 目标频道模板（分类标题 + 频道名，决定输出内容）
├── result.txt          # TXT 格式输出（运行时实时写入）
├── result.m3u          # M3U 格式输出（运行时实时写入）
├── requirements.txt    # Python 依赖
└── logs/               # 日志目录（运行时生成）
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
    ↓ on_pass_callback → 实时写入
result.txt + result.m3u
```

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
- **输出**：`save_result_txt()` / `save_result_m3u()` → 只输出通过的频道，空分类跳过
- **定时调度**：`_next_run_datetime()` + `__main__` 循环，绝对时间触发，无漂移
- **带宽限速**：`SystemDownloadLimiter` → 用 `psutil` 采样系统总下行，超过阈值暂停新测试

### FFmpegTest.py

- `ffmpeg_test(url)`：调 FFmpeg 探测分辨率
- `analyze_iptv_with_ffmpeg(url, duration)`：完整测速入口（探测 + 带宽）
- `test_direct_bandwidth()` / `test_hls_bandwidth()`：分协议测带宽
- `_timed_out_urls`：超时 URL 注册表，流读取循环中检测并主动退出，触发连接关闭
- `register_timeout(url)`：app.py 超时时调用，标记该 URL

---

## 配置体系

所有配置集中在 `config.json`，app.py 通过 `load_config()` 读取，`server.py` 通过 `load_config()` 同步。配置项缺失时自动使用 `DEFAULT_CONFIG` 中的默认值。

**运行模式**（`run_mode`）：
- `once`：运行一次退出
- `times`：按 `run_times` 列表指定的时间循环执行，支持跨天
- `interval`：每轮结束后等待 `run_interval_minutes` 分钟再执行，从结束时刻开始计，无漂移

**筛选阈值全部走 config**，不在代码里硬编码：
- `min_width` / `min_height`：最低分辨率
- `min_bandwidth_MBps`：最低带宽
- `bandwidth_compensation_MBps`：未获取分辨率时的补偿阈值
- `system_bandwidth_limit_MBps`：系统总下行限速

---

## 关键设计决策

1. **别名正则预编译**：`load_aliases` 在启动时一次性编译所有 `re:` 别名，运行时用预编译对象匹配，避免每次调用 `re.match` 解析正则字符串
2. **实时写入**：每个频道通过测速后立即触发 `on_pass_callback`，用 `threading.Lock` 保护 `filtered_urls` 和文件写入，不会到最后才输出
3. **连接泄漏修复**：超时时调用 `register_timeout(url)`，FFmpegTest 流读取循环每读一个 chunk 检查 `_is_timed_out()`，命中立即 break，触发 `with` 块的 `response.close()`；`executor.shutdown(wait=True)` 确保所有线程结束后再返回
4. **带宽单位**：`SystemDownloadLimiter` 使用 MB/s（兆字节/秒），不是 Mbps（兆比特/秒），config 里的单位说明要写清楚
5. **绝对时间调度**：不用 `sleep(固定秒数)`，而是每次计算 `next_run = now + interval`，一轮结束后重新计算，避免时间漂移

---

## 常见修改场景

### 调整筛选标准

编辑 `config.json` 中的 `min_bandwidth_MBps`、`min_width`、`min_height`，不动代码。

### 添加新频道别名

在 `alias.txt` 中按格式添加行：`主名,别名1,re:正则,...`

### 更换输出的 EPG 地址

修改 `app.py` 中 `save_result_m3u()` 函数里的 `#EXTM3U x-tvg-url="..."`。

### 修改 M3U 输出的 logo 地址模板

修改 `save_result_m3u()` 里的 `logo_base` 变量。

### 添加新的配置项

1. 在 `config.json` 中添加 key（同时加 `# key` 注释行）
2. 在 `app.py` 的 `DEFAULT_CONFIG` 字典中添加默认值
3. 在需要使用的地方通过 `cfg['key']` 读取

### 修改测速判定逻辑

`test_iptv_quality()` 和 `filter_and_save_playlist()` 内的 `test_single_channel()` 是两处判定逻辑，修改时两处都要改（它们用相同的 `min_width` / `min_bw` / `bw_comp` 变量）。

---

## 编码规范

- 所有配置走 `config.json`，不在代码里硬编码魔法数字
- 频道名匹配统一走 `match_channel_name()`，不自行判断
- HTTP 请求统一走 `FFmpegTest.http_get()`，不直接用 `requests.get()`
- 文件路径统一用配置项，不硬编码文件名
- 中文注释和日志，面向国内用户

---

## 运行方式

```bash
# 安装依赖
pip install -r requirements.txt

# 单次运行
python app.py

# 定时运行：修改 config.json 的 run_mode 后运行，Ctrl+C 退出
python app.py
```

Windows 环境下使用 PyCharm，虚拟环境建议建在项目目录下 `.venv`，解释器指向 `.venv/Scripts/python.exe`。

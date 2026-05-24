# IPTV 频道质量筛选工具

## 简介

从多个 M3U 订阅源中筛选高质量 IPTV 频道（1080P + 高带宽），支持频道别名识别、模板化输出、实时写入和定时执行。

---

## 核心功能

- 多订阅源聚合，自动解析 M3U 播放列表
- FFmpeg 分辨率探测 + 带宽测速
- 频道别名识别（精确匹配 + 正则），同一频道多个名字自动归一
- 按模板文件（demo.txt）决定测哪些频道，跳过不需要的
- 测速通过实时写入 result.txt 和 result.m3u，不等全部完成
- 超时自动中断 HTTP 连接，无残留
- 系统级下行带宽限速，防止打满带宽
- 定时执行：固定时间 / 间隔循环 / 单次运行

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
# 需要系统已安装 FFmpeg
```

### 2. 准备配置文件

项目根目录放置以下文件：

| 文件 | 作用 | 格式 |
|------|------|------|
| `config.json` | 所有可配置项 | JSON |
| `subscribe.txt` | M3U 订阅源地址，每行一个 | 纯文本 |
| `alias.txt` | 频道别名映射，支持正则 | CSV |
| `demo.txt` | 目标频道模板，决定输出哪些频道 | 分类 + 频道名 |

### 3. 运行

```bash
python app.py
```

---

## 配置文件说明

### config.json

```json
{
    "test_duration": 15,
    "max_workers": 30,
    "system_bandwidth_limit_MBps": 50,
    "min_bandwidth_MBps": 1.0,
    "bandwidth_compensation_MBps": 2.0,
    "min_width": 1920,
    "min_height": 1080,
    "alias_file": "alias.txt",
    "demo_file": "demo.txt",
    "subscribe_file": "subscribe.txt",
    "output_txt": "result.txt",
    "output_m3u": "result.m3u",
    "run_mode": "once",
    "run_times": ["06:00", "12:00", "18:00"],
    "run_interval_minutes": 120
}
```

**配置项说明：**

| 配置项 | 类型 | 说明 |
|--------|------|------|
| `test_duration` | int | 每个频道测速时长（秒） |
| `max_workers` | int | 最大同时测试频道数（并发线程） |
| `system_bandwidth_limit_MBps` | float | 系统下行带宽限速（MB/s），超过暂停新测试，0 关闭 |
| `min_bandwidth_MBps` | float | 频道带宽合格标准（MB/s） |
| `bandwidth_compensation_MBps` | float | 未获取分辨率时的带宽补偿阈值（MB/s） |
| `min_width` / `min_height` | int | 最低分辨率要求（像素） |
| `run_mode` | string | `once` 单次运行 / `times` 按指定时间 / `interval` 按间隔 |
| `run_times` | list | `times` 模式下的执行时间列表，24 小时制 |
| `run_interval_minutes` | int | `interval` 模式的间隔分钟数，从上一轮结束开始计 |

---

### subscribe.txt

每行一个 M3U 数据源地址，空行和 `#` 开头的行忽略：

```
https://example.com/playlist1.m3u
https://example.com/playlist2.m3u
```

---

### alias.txt

将多个频道名映射到同一个主名，提升匹配率：

```
# 格式：主名,别名1,别名2,re:正则表达式
CCTV-1,re:(?i)^\s*CCTV[-\s_]*0?1(?![0-9Kk+])[\s\S]*$,CCTV1,CCTV-01高清,CCTV1综合
```

- 第一列是主名（对应 demo.txt 中的频道名）
- 以 `re:` 开头的为正则表达式，自动按正则匹配
- 其余为精确匹配别名

---

### demo.txt

定义要测哪些频道和分类结构，只有这里出现的频道才会被测试和输出：

```
📺央视频道,#genre#
CCTV-1
CCTV-5

📡卫视频道,#genre#
广东卫视
浙江卫视
```

- 包含 `,#genre#` 的行是分类标题
- 其余每行一个频道名（使用主名）
- demo.txt 为空时不进行任何测试

---

## 输出格式

### result.txt

```
🕘️更新时间,#genre#
2026-05-24 18:00:00,邮箱联系

📺央视频道,#genre#
CCTV-1,http://example.com/cctv1.m3u8
CCTV-5,http://example.com/cctv5.m3u8
CCTV-5,http://example.com/cctv5_bak.m3u8

📡卫视频道,#genre#
广东卫视,http://example.com/gdws.m3u8
```

- 同一频道多个 URL 都通过测速时输出多条
- 没有通过测速的频道不输出
- 空分类不输出

### result.m3u

标准 M3U 格式，可直接导入 VLC / IPTV 播放器 / 电视盒子。

---

## 运行模式

### 单次运行（once）

```json
"run_mode": "once"
```

运行一次，完成退出。

### 按指定时间循环（times）

```json
"run_mode": "times",
"run_times": ["06:00", "12:00", "18:00"]
```

程序持续运行，到达指定时间自动执行，支持跨天，Ctrl+C 退出。

### 按间隔循环（interval）

```json
"run_mode": "interval",
"run_interval_minutes": 120
```

每轮结束后等待指定分钟数再执行下一轮，不会时间漂移，Ctrl+C 退出。

---

## 项目文件结构

```
IPTV-Test/
├── app.py              # 核心逻辑 + 命令行入口（含定时调度）
├── FFmpegTest.py       # FFmpeg 分辨率探测 + 带宽测速
├── config.json         # 配置文件
├── subscribe.txt       # M3U 订阅源地址
├── alias.txt           # 频道别名映射
├── demo.txt            # 目标频道模板
├── requirements.txt    # Python 依赖
├── output/             # 输出目录（运行后自动生成）
│   ├── result.txt      # TXT 格式输出
│   └── result.m3u      # M3U 格式输出
└── logs/               # 日志目录（运行后自动生成）
```

---

## 常见问题

**Q: FFmpeg 未找到**  
安装 FFmpeg 并确保在 PATH 中：`yum install -y ffmpeg` 或 `apt install ffmpeg`

**Q: 所有频道都不通过**  
在 config.json 中降低标准：调小 `min_bandwidth_MBps` 或 `min_width` / `min_height`

**Q: 内存不足**  
减小 `max_workers`，建议 5~10

**Q: 频道名字不一样匹配不上**  
在 alias.txt 中添加对应的别名或正则

**Q: 跑完后系统还有连接在跑**  
已在代码中处理：超时连接会主动中断，线程池等待全部结束后才退出

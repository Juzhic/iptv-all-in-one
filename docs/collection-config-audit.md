# 采集配置与平台接口核对（2026-09-14）

本次核对基于 Git、官方公开文档、实际调用链以及模拟 HTTP/数据库的回归测试。没有使用真实 Key 发起付费搜索，也没有据此认定任何账号已经恢复权限。

## Hunter：8 月 24 日之后发生了什么

| 时间 | 已核实的变化 | 与当前报错的关系 |
| --- | --- | --- |
| 2026-08-24 14:43:26 +0800 | 当日最后提交 `0199425`，版本 2.0.6 | 用户确认同一账号、同一 Key 当时通过程序采集成功 |
| 2026-08-27 | `ac57e72`：Tvheadend、IPTV 互动扫描每页 50 改为最多 10；互动查询 `title:` 改为 `web.title:`；修复停止状态引用 | 专用扫描参数发生变化，不能解释账号权限变化；标题冒号语法仍存在错误，本次改为等号 |
| 2026-08-28 | `468f977`：迁移 PostgreSQL | 配置存储发生变化；Hunter 账号接口和主查询实现没有变化 |
| 2026-09-07 | Hunter 官方 v3.0.1：增加按账号权限开放的 IPv6、CNAME/MX 查询，优化导出和 DNS 信息 | 公告未宣布个人 API 全面改为付费，不能推断它导致当前权限错误 |

从 `0199425` 到本次修改前的 HEAD，`key_manager.py` 与 `platforms/hunter.py` 的 Git 差异为空。原余额逻辑一直是先请求 `GET /openApi/userInfo`，失败后再请求 `/openApi/search`，查询内容为 `test`，并把后一次错误展示给用户。故原界面的“账号无 API 访问权限，需升级为付费账号”可能来自搜索回退，不能代表账号信息接口的原始响应。

现在余额只查询 `userInfo`，搜索只使用 `search`；错误保留接口名、HTTP 状态、业务 code 和脱敏后的 message。免费积分与权益积分同时参与余额计算；缺失值不是零，`-1` 按无限额处理。HTTP 403 不再直接停用 Key，只有明确的积分耗尽信息触发轮换。

公开帮助页的“哪些语法/功能需要付费使用”（标注更新于 2023-04-26）仍说明未列出的普通语法无需充值，普通正文/标题不在所列特色语法中。这不等同于对当前账号 API 权限的保证。若更新后仍报错，应以新的 `userInfo` 或 `search` 诊断为准；目前没有证据确定权限为何在该账号上变化。

## FOFA 调用核对

| 用途 | 实现 |
| --- | --- |
| 账号和余额 | `GET https://fofa.info/api/v1/info/my`，仅必需 Key，邮箱可选 |
| 主查询与画像 | `GET /api/v1/search/all`，UTF-8 标准 Base64，`ip,port,region,city` 字段，正确的 page/size |
| 余额显示 | F 币、F 点、免费 F 点、月度查询剩余次数、月度数据剩余条数分别显示；未知和零区分 |
| 运营商 | `org` 常见组织别名匹配，不再使用未支持的 `isp`；准确覆盖范围受 FOFA ASN 组织数据影响 |
| 异常和资源 | 限流/临时网络异常重试、同 Key 请求间隔、禁止携带 Key 跟随跳转、异常脱敏、部分结果保留、关闭自建会话 |

项目中的 FOFA 主查询及质量画像均经过公共 `request_fofa`；未发现另一个绕过该辅助函数的 FOFA HTTP 入口。

## 配置保存到执行的对应关系

页面保存经 `/api/scan/config` 写入数据库，后端合并未提交字段、保留独立管理的 Key，并通知调度器重载。每轮全量或增量采集固定使用开始时的配置快照，保存新值影响下一轮；正在运行的采集不会混用新旧预算。数据库读取失败或存储 JSON 损坏会明确报错，不再作为“默认配置加载成功”。

| 页面配置 | 执行位置 | 实际范围/条件 |
| --- | --- | --- |
| 平台 Key、FOFA 邮箱 | `key_manager`、平台扫描器 | Key 管理独立保存；FOFA 邮箱不参与必需鉴权 |
| 采集平台 `enabled_platforms` | `collector.collect_all` | 明确选择时只使用所选 API 平台；留空按省积分策略自动选 |
| 省份、运营商 | `collector` 查询过滤 | API 主查询、质量画像；Hunter 专用扫描也传入筛选。社区、历史热点、DDGS、全国补扫并非按这些 API 条件过滤 |
| 四个平台的采集数量 | `collector._target_for` → 各平台扫描器 | 每个平台、每个所选省份的主查询目标，画像和非省积分模式的独立补扫另计；不是最终频道条数 |
| 主采集关键词 | `config_bridge.build_search_queries` | 四个平台的主查询；不替换质量画像、专用接口指纹或 DDGS 规则 |
| 省积分模式 | `collector.collect_all` | 留空平台时按 Quake → FOFA → Hunter → DayDayMap 选一个；跳过独立 ZHGX/JSMpeg/Tvheadend/互动及宽泛域名补扫。不声称根据历史收益自动筛选画像 |
| C 段开关、单段 IP 上限 | `ip_extract.smart_c_segment_scan` | 仅在已有成功源时扩展 IPv4 /24，关闭后立即跳过 |
| C 段全局网段/IP 上限 | `CScanBudget` | 一轮 API 平台及画像共享预算；/24 与端口组成一次扩展，缓存避免近期重复探测 |
| C 段单来源网段/IP 上限 | `CScanBudget.reserve` | 按平台/画像的来源统计对象分配，不代表每个频道各有一份预算 |
| DDGS 开关 | `collector` → `ddgs_scan` | 独立公共搜索补源，仅开启时调用 |
| 时间、星期、每天执行 | `_daily_update_task` | 北京时间；每天开启时忽略星期限制；关闭每天并清空星期即停用定时采集，手动采集仍可运行 |
| 质量优先查询开关 | `collector` | 控制额外画像查询；关闭时也跳过质量独立补扫；不关闭历史质量热点开关 |
| 画像查询预算 | `collector` 分配任务 | 每个画像平台的总目标，按省份×画像分配，零预算任务跳过；不会因强制每组至少一条而超额 |
| 质量热点开关/IP:端口预算 | `scan_quality_hotspots` | 全量和增量均执行；基于历史高质量源，不依赖当轮 API 是否命中 |
| 历史源最低稳定性 | `isp_intelligence` 质量热点候选构建 | 筛选历史样本；不是本轮深测通过阈值 |
| 深测最低带宽、最大延迟、最低稳定性 | `get_quality_thresholds`、`quality_gate_failure` | 检测和持久化使用同一阈值；带宽单位 MB/s |
| 深测时长、最少采样字节、单请求超时 | `video_check.get_deep_check_options` → 深测 | 动态参数传入检测；达不到采样/质量要求时不能仅因 URL 可访问而通过 |
| ISP 热点开关、最少频道数 | `get_hot_segments`、`scan_hot_segments` | 全量与增量均执行；从历史频道识别热点，最多取前 50 个候选网段 |
| 热点 IP 探测预算 | `scan_hot_segments` | 限制实际抽样 IP 总量，原“最多网段数”文案不正确，已修复 |
| 社区源开关、URL 列表 | `scan_community_sources` | 全量与增量均执行；自定义 URL 追加到内置列表并去重。输入须为含 EXTINF 的 M3U 内容直链；仓库首页和普通频道 CSV/TXT 不是 M3U |
| GitHub 代理 | `community_sources._apply_proxy` | 仅社区来源的 GitHub 资源；留空直连，不再自动选择公共代理，也不改变其他 API 的网络代理 |

尚未在页面暴露的 `quality_discovery_platforms`、`quality_query_profiles`、深测并发等高级字段仍由数据库配置维护。表单保存仅提交自己的字段，不会把上次响应中的隐藏高级字段附带覆盖。当前内置画像为 TXIPTV、标准直播接口、ZHGXTV、Tvheadend 四组；历史配置中没有对应实现的画像名称会被清理，全部失效时回到这四个默认画像，避免开启画像却没有任务。

## 关键词调整

- 默认规则保留 `/tsfile/live/ && key=txiptv`、`/iptv/live/zh_cn.js`、`/iptv/live/1000.json`、`/ZHGXTV/Public/json/live_interface.txt`。带 `?key=txiptv` 的 1000.json 规则被不带参数的正文匹配覆盖，从新默认值中移除。
- 自定义数据库规则不会被新默认值强行覆盖。页面可点击“恢复默认”并保存；同一行重复条件和重复查询表达式在生成时去重。
- Quake 使用 `body:"..."`、`title:"..."`、`AND/OR`、`province_cn:"..."`、`isp:"..."`；Hunter 使用 `web.body="..."`、`web.title="..."`、`&&/||`、`ip.province`、`ip.isp`；FOFA/DayDayMap 使用等号正文/标题条件与 `&&/||`。
- 主查询不会无条件扩展为 `tv`、`live`、`hotel`。域名候选缩小到 `iptv`、`txiptv`、`zhgx`，去掉宽泛且重复的证书通配项；省积分模式跳过此补扫。Censys 保留独立环境变量鉴权的旧集成，未做真实 Censys 账号兼容性验证。
- 质量画像与主规则会有部分重叠，这是为不同接口族单独分配检索预算；不等于零额外消费。关闭“质量优先查询”可关闭这部分查询，画像预算不包含非省积分模式的专用补扫。
- 不承诺关键词优化后必然提高有效频道数：平台索引时间、可检索字段权限、源站状态和深测阈值都会影响产出。

## 验证与来源

新增测试覆盖 Hunter 余额接口不回退、免费/权益/无限额、错误脱敏、权限与耗尽区分、分页不重不超额、持久化读取与任务快照、社区代理、增量来源开关、实际查询平台/省份/预算，以及配置读取失败。既有 FOFA、停止状态、质量门槛、C 段预算、密钥存储和来源追踪测试也参与回归。前端覆盖保存/回填、加载失败、隐藏字段、空关键词、未保存状态和余额展示。

- [FOFA API 文档](https://fofa.info/api/info)
- [Hunter 账号信息](https://hunter.qianxin.com/home/helpCenter?r=5-1-4)
- [Hunter 搜索接口](https://hunter.qianxin.com/home/helpCenter?r=5-1-2)
- [Hunter 基础语法](https://hunter.qianxin.com/home/helpCenter?r=8-1)
- [Hunter 更新日志](https://hunter.qianxin.com/home/changelog)
- [Quake 官方帮助：查询语句与 API](https://quake.360.net/quake/#/help)

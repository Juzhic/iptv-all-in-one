# 组播模板来源

本目录的 TXT 文件来自 [maowei1125/spider-iptv](https://github.com/maowei1125/spider-iptv)，
固定版本 `ba1f1dea5f878f2ac536790418e81b4f25f3cb75`（上游最后推送日期 2024-07-15），
导入日期 2026-09-16。来源路径为 `source/multicast/*.txt`；保留非空文件的原始内容，
许可证见本目录 [LICENSE](LICENSE)（Apache License 2.0）。

这些文件是历史频道地址资料，不代表当前可用源。运行时仅提取有效的 IPv4 组播地址、
频道名称和 RTP/UDP 类型；忽略广告、非组播地址、HTML 错误页及重复地址。
文件中的旧 HTTP 代理主机不用于探测或播放。实际代理来自管理员填写的地址或 Quake 搜索。
同一省份和运营商下的自定义模板替换对应内置模板。

本项目自行实现异步采集和模板解析，没有引入上游 Python 脚本、MySQL 数据库或测速实现。

# iptv-all-in-one

从多个 M3U 订阅源中筛选可用且质量较高的 IPTV 频道，支持 FFmpeg 分辨率检测、带宽测速、频道别名归一、模板化输出、Web 后台配置、历史记录和定时运行。

集成 IPTV 频道扫描模块，可通过搜索引擎 API（Quake / Hunter / DayDayMap / Fofa）自动发现酒店 IPTV 服务器，提取频道列表并送入测速流水线。

## 快速开始

```yaml
# docker-compose.yml
services:
  iptv-all-in-one:
    image: juzhic/iptv-all-in-one:latest
    ports:
      - "58080:58080"
    environment:
      DB_HOST: mysql
      DB_PORT: 3306
      DB_USER: ${DB_USER:-iptv_app}
      DB_PASSWORD: ${DB_PASSWORD:?请先运行 python generate_env.py}
      DB_NAME: ${DB_NAME:-iptv-all-in-one}
      IPTV_AUTH_USERNAME: ${IPTV_AUTH_USERNAME:-admin}
      IPTV_AUTH_PASSWORD: ${IPTV_AUTH_PASSWORD:?请先运行 python generate_env.py}
      IPTV_SECRET_KEY: ${IPTV_SECRET_KEY:?请先运行 python generate_env.py}
      IPTV_OUTPUT_DIR: /app/output
      IPTV_REQUIRE_STRONG_CREDENTIALS: "1"
    volumes:
      - app_data:/app/data
      - app_output:/app/output
    read_only: true
    tmpfs:
      - /tmp:rw,noexec,nosuid,nodev,size=64m,uid=10001,gid=10001,mode=1777
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    depends_on:
      - mysql
    restart: unless-stopped

  mysql:
    image: mysql:8.4
    environment:
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD:?请先运行 python generate_env.py}
      MYSQL_DATABASE: ${DB_NAME:-iptv-all-in-one}
      MYSQL_USER: ${DB_USER:-iptv_app}
      MYSQL_PASSWORD: ${DB_PASSWORD:?请先运行 python generate_env.py}
    volumes:
      - mysql_data:/var/lib/mysql
    restart: unless-stopped

volumes:
  mysql_data:
  app_data:
  app_output:
```

```bash
# .env
MYSQL_ROOT_PASSWORD=<独立的随机 root 密码>
DB_HOST=mysql
DB_PORT=3306
DB_USER=iptv_app
DB_PASSWORD=<独立的随机应用数据库密码>
DB_NAME=iptv-all-in-one
IPTV_AUTH_USERNAME=admin
IPTV_AUTH_PASSWORD=<独立的随机管理密码>
IPTV_SECRET_KEY=<至少 32 字节的随机加密主密钥>
```

```bash
# 推荐在项目根目录先生成稳定强凭据
python generate_env.py
docker compose up -d
```

访问 `http://localhost:58080` 进入 Web 管理后台，使用 `.env` 中的 `IPTV_AUTH_USERNAME` 和 `IPTV_AUTH_PASSWORD` 登录。Docker 模式缺少强凭据时会拒绝启动。

默认端口绑定所有网卡，匿名 TXT/M3U 订阅也会继续公开；请使用防火墙、VPN 或反向代理限制管理界面的访问范围。

## 主要功能

**测速模块**
- 聚合多个 M3U 订阅源，按频道模板精准匹配
- FFmpeg 分辨率检测 + 带宽采样测速
- H.265/HEVC 编码带宽折算
- 频道别名归一（精确 + 正则）
- 定时运行（once / times / interval 三种模式）
- 实时写入 TXT / M3U 输出文件

**扫描模块**
- Quake / Hunter / DayDayMap / Fofa 四平台扫描
- 多 Key 轮换 + 积分余额查询
- 质量优先画像查询（txiptv_live / live_interface / zhgx / tvheadend 等）
- C 段扩展扫描 + 质量热点补源
- 省份 / 城市 / 运营商过滤
- 扫描收益统计（按平台/画像维度）

**检测与运维**
- 持久化结果定期检测，自动移除失效频道
- 检测概览 + 轮次状态 + 质量分档
- 可见页面自适应轮询，保留受限 SSE 兼容接口
- MySQL 数据存储，自动重连 + 启动重试
- Docker Compose 内置 MySQL 8.4，开箱即用
- 低内存调优参数，适配小内存服务器

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DB_HOST` | MySQL 主机 | (读取 db_config.json) |
| `DB_PORT` | MySQL 端口 | 3306 |
| `MYSQL_ROOT_PASSWORD` | MySQL root 密码，仅数据库初始化/迁移使用 | (必填) |
| `DB_USER` | 应用专用 MySQL 用户 | iptv_app |
| `DB_PASSWORD` | MySQL 密码 | (必填) |
| `DB_NAME` | 数据库名 | iptv-all-in-one |
| `IPTV_AUTH_PASSWORD` | Web 后台密码 | (必填) |
| `IPTV_SECRET_KEY` | API Key 加密主密钥 | (必填) |
| `IPTV_OUTPUT_DIR` | 固定结果文件目录 | /app/output |
| `FFMPEG_BIN` | FFmpeg 路径 | /usr/bin/ffmpeg |

## 技术栈

Python 3.12 / Flask / Gunicorn / aiohttp / pymysql / Vue 3 / TDesign / Vite / MySQL 8.4 / FFmpeg / Docker Compose

---

## 更新日志

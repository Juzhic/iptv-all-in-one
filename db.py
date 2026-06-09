"""IPTV 测速结果 SQLite 数据库模块。"""
import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

DB_PATH = 'iptv.db'
MAX_RUNS = 50
CONFIG_DATA = 'config'  # config_data 表中存储系统配置的 key
LOCAL_TZ = timezone(timedelta(hours=8))


def now_str():
    return datetime.now(LOCAL_TZ).strftime('%Y-%m-%d %H:%M:%S')


def timestamp_str(ts):
    return datetime.fromtimestamp(ts, LOCAL_TZ).strftime('%Y-%m-%d %H:%M:%S')

# ─── 内置默认 demo 模板 ───
DEFAULT_DEMO = """📢公告,#genre#
添加频道联系1261334596@qq.com

📺央视频道,#genre#
CCTV-1
CCTV-2
CCTV-3
CCTV-4
CCTV-5
CCTV-5+
CCTV-6
CCTV-7
CCTV-8
CCTV-9
CCTV-10
CCTV-11
CCTV-12
CCTV-13
CCTV-14
CCTV-15
CCTV-16
CCTV-17
CETV-1
CETV-2
CETV-3
CETV-4

💰央视付费频道,#genre#
文化精品
央视台球
风云音乐
第一剧场
风云剧场
怀旧剧场
女性时尚
高尔夫网球
风云足球
电视指南
世界地理
兵器科技

📡卫视频道,#genre#
广东卫视
香港卫视
浙江卫视
湖南卫视
北京卫视
湖北卫视
黑龙江卫视
安徽卫视
重庆卫视
东方卫视
东南卫视
甘肃卫视
广西卫视
贵州卫视
海南卫视
河北卫视
河南卫视
吉林卫视
江苏卫视
江西卫视
辽宁卫视
内蒙古卫视
宁夏卫视
青海卫视
山东卫视
山西卫视
陕西卫视
四川卫视
深圳卫视
三沙卫视
天津卫视
西藏卫视
新疆卫视
云南卫视

☘️广东频道,#genre#
广东珠江
广东体育
广东新闻
广东卫视
广东民生

🌊港·澳·台,#genre#
翡翠台
明珠台
凤凰中文
凤凰资讯
凤凰香港
凤凰卫视
TVBS亚洲
香港卫视
纬来体育
纬来育乐
J2
Viutv
三立台湾
无线新闻
三立新闻
东森综合
东森超视
东森电影
Now剧集
Now华剧
靖天资讯
星卫娱乐
卫视卡式

🎮游戏频道,#genre#
游戏风云
游戏竞技
电竞游戏
海看电竞
电竞天堂
爱电竞

🎵音乐频道,#genre#
CCTV-15
风云音乐
音乐现场
音乐之声
潮流音乐
天津音乐
音乐广播
音乐调频广播

🎬电影频道,#genre#
CHC家庭影院
CHC动作电影
CHC高清电影
淘剧场
淘娱乐
淘电影
NewTV惊悚悬疑
NewTV动作电影
黑莓电影
纬来电影
靖天映画
靖天戏剧
星卫娱乐
艾尔达娱乐
经典电影
IPTV经典电影
天映经典
无线星河
星空卫视
私人影院
东森电影
龙祥电影
东森洋片
东森超视

🏀体育频道,#genre#
CCTV-5
CCTV-5+
广东体育
纬来体育
五星体育
体育赛事
劲爆体育
爱体育
超级体育
精品体育
广州竞赛
深圳体育
福建体育
辽宁体育
山东体育
成都体育
天津体育
江苏体育
安徽综艺体育
吉林篮球
睛彩篮球
睛彩羽毛球
睛彩广场舞
风云足球
足球频道
魅力足球
天元围棋
快乐垂钓
JJ斗地主""".lstrip()

# ─── 内置默认 alias 别名 ───
DEFAULT_ALIAS = r"""# 这是频道名称的别名名单，用于获取接口时将多种名称映射为一个名称的结果，可以提升获取量与准确率
# 格式：主名（对应demo.txt模板中的频道名称）,别名1,别名2,别名3
# 支持使用正则表达式匹配别名，以re:开头的别名将被识别为正则表达式

CCTV-1,re:(?i)^\s*CCTV[-\s_]*0?1(?![0-9Kk+])[\s\S]*$,CCTV1,CCTV-01,CCTV-01_ITV,CCTV-01高清,CCTV1综合,CCTV-1综合,CCTV1HD,CCTV-1HD,CCTV1-标清,CCTV-1高清
CCTV-2,re:(?i)^\s*CCTV[-\s_]*0?2(?![0-9Kk+])[\s\S]*$,CCTV2,CCTV-02高清,CCTV2财经,CCTV-2财经,CCTV2HD,CCTV-2HD,CCTV2-标清,CCTV2-财经
CCTV-3,re:(?i)^\s*CCTV[-\s_]*0?3(?![0-9Kk+])[\s\S]*$,CCTV3,CCTV-03,CCTV3综艺,CCTV-3综艺,CCTV3HD,CCTV-3HD,CCTV3-标清
CCTV-4,re:(?i)^\s*CCTV[-\s_]*0?4(?![0-9Kk+])(?!.*(?:欧洲|美洲|Europe|America|Americas))[\s\S]*$,CCTV4,CCTV-04,CCTV4HD,CCTV-4HD,CCTV-4标清
CCTV-5,re:(?i)^\s*CCTV[-\s_]*0?5(?![0-9Kk+])[\s\S]*$,CCTV5,CCTV-05,CCTV5体育,CCTV-5体育,CCTV5HD,CCTV-5HD
CCTV-5+,re:(?i)^\s*CCTV[-\s_]*0?5\s*(?:\+|＋)[\s\S]*$,CCTV5+,CCTV5＋,CCTV5+体育赛事,CCTV-5+体育赛事,CCTV5+HD,CCTV-5+HD
CCTV-6,re:(?i)^\s*CCTV[-\s_]*0?6(?![0-9Kk+])[\s\S]*$,CCTV6,CCTV-06,CCTV6电影,CCTV-6电影,CCTV6HD,CCTV-6HD
CCTV-7,re:(?i)^\s*CCTV[-\s_]*0?7(?![0-9Kk+])[\s\S]*$,CCTV7,CCTV-07,CCTV7 国防军事,CCTV-7国防军事,CCTV7HD,CCTV-7HD
CCTV-8,re:(?i)^\s*CCTV[-\s_]*0?8(?![0-9Kk+])[\s\S]*$,CCTV8,CCTV-08,CCTV8 电视剧,CCTV-8电视剧,CCTV8HD,CCTV-8HD
CCTV-9,re:(?i)^\s*CCTV[-\s_]*0?9(?![0-9Kk+])[\s\S]*$,CCTV9,CCTV-09,CCTV9 纪录,CCTV-9纪录,CCTV9HD,CCTV-9HD
CCTV-10,re:(?i)^\s*CCTV[-\s_]*0?10(?![0-9Kk+])[\s\S]*$,CCTV10,CCTV10 科教,CCTV-10科教,CCTV10HD,CCTV-10HD
CCTV-11,re:(?i)^\s*CCTV[-\s_]*0?11(?![0-9Kk+])[\s\S]*$,CCTV11,CCTV11 戏曲,CCTV-11戏曲,CCTV11HD,CCTV-11HD
CCTV-12,re:(?i)^\s*CCTV[-\s_]*0?12(?![0-9Kk+])[\s\S]*$,CCTV12,CCTV12 社会与法,CCTV-12社会与法,CCTV12HD,CCTV-12HD
CCTV-13,re:(?i)^\s*CCTV[-\s_]*0?13(?![0-9Kk+])[\s\S]*$,CCTV13,CCTV13 新闻,CCTV-13新闻,CCTV13HD,CCTV-13HD
CCTV-14,re:(?i)^\s*CCTV[-\s_]*0?14(?![0-9Kk+])[\s\S]*$,CCTV14,CCTV14 少儿,CCTV-14少儿,CCTV14HD,CCTV-14HD
CCTV-15,re:(?i)^\s*CCTV[-\s_]*0?15(?![0-9Kk+])[\s\S]*$,CCTV15,CCTV15 音乐,CCTV-15音乐,CCTV15HD,CCTV-15HD
CCTV-16,re:(?i)^\s*CCTV[-\s_]*0?16(?![0-9Kk+])[\s\S]*$,CCTV16,CCTV16 4K,CCTV-16 4K,CCTV16HD,CCTV-16HD
CCTV-17,re:(?i)^\s*CCTV[-\s_]*0?17(?![0-9Kk+])[\s\S]*$,CCTV17,CCTV17 农业农村,CCTV-17农业农村,CCTV17HD,CCTV-17HD
CCTV-4美洲,re:(?i)^\s*CCTV[-\s_]*0?4(?![0-9Kk+])[\s\S]*\b(?:美洲|America|Americas)\b[\s\S]*$
CCTV-4欧洲,re:(?i)^\s*CCTV[-\s_]*0?4(?![0-9Kk+])[\s\S]*\b(?:欧洲|Europe)\b[\s\S]*$
CCTV-4K,re:(?i)^\s*CCTV[-\s_]*0?4(?![0-9])\s*(?:[Kk]|Ｋ)\b[\s\S]*$,CCTV4K,CCTV4K超高清,CCTV-4K超高清
CCTV-8K,re:(?i)^\s*CCTV[-\s_]*0?8(?![0-9])\s*(?:[Kk]|Ｋ)\b[\s\S]*$,CCTV8K,CCTV8K超高清,CCTV-8K超高清

兵器科技,CCTV兵器,CCTV兵器科技,CCTV-兵器科技
第一剧场,CCTV第一剧场,CCTV-第一剧场
发现之旅,CCTV发现之旅,CCTV-发现之旅
风云剧场,CCTV风云剧场,CCTV-风云剧场
风云音乐,CCTV风云音乐,CCTV-风云音乐
风云足球,CCTV风云足球,CCTV-风云足球
央视台球,CCTV央视台球,CCTV-央视台球
高尔夫网球,CCTV高尔夫球,CCTV高尔夫·网球,CCTV-高尔夫网球
怀旧剧场,CCTV怀旧剧场,CCTV-怀旧剧场
老故事,CCTV老故事,CCTV-老故事
女性时尚,CCTV女性时尚,CCTV-女性时尚
世界地理,CCTV世界地理,CCTV-世界地理
文化精品,CCTV文化精品,CCTV-文化精品
百姓健康,CCTV卫生健康,CCTV-卫生健康
中学生,CCTV中学生,CCTV-中学生

CETV-1,CETV1,CETV1中国教育,中国教育1
CETV-2,CETV2,CETV2中国教育,中国教育2
CETV-3,CETV3,CETV3中国教育,中国教育3
CETV-4,CETV4,CETV4中国教育,中国教育4

广东珠江,GDTV-2,珠江,珠江频道,珠江台
广东卫视,广东卫视高清,广东卫视HD
翡翠台,TVb翡翠台,tvb翡翠台,TVB翡翠台
明珠台,TVb明珠台,tvb明珠台,TVB明珠台
凤凰中文,凤凰卫视中文台
凤凰香港,凤凰卫视香港台
凤凰资讯,凤凰资讯台HD

无线新闻台,無綫新聞台,無線新聞台,无线新闻,TVB无线新闻
港台电视 31,港台電視 31,RTHK31
港台电视 32,港台電視 32,RTHK32

北京卡酷少儿,卡酷少儿,卡酷少儿高清,卡酷少儿HD

黑莓电影,NewTV黑莓电影
黑莓动画,NewTV黑莓动画
家庭剧场,NewTV家庭剧场
惊悚悬疑,NewTV惊悚悬疑
超级电影,NewTV超级电影
动作电影,NewTV动作电影
游戏风云,SiTV游戏风云
动漫秀场,SiTV动漫秀场
爱动漫,iHOT爱动漫
新动漫,iHOT新动漫
电竞天堂,BesTV电竞天堂
宝宝动画,BesTV宝宝动画
嘉佳卡通,广东嘉佳卡通
金鹰卡通,湖南金鹰卡通
哈哈炫动,炫动卡通,上海哈哈炫动
优漫卡通,江苏优漫卡通

四川卫视,四川卫视4K
湖南卫视,湖南卫视4K
北京卫视,北京卫视4K""".lstrip()

_local = threading.local()


def _get_conn():
    """每个线程获取独立的数据库连接。"""
    if not hasattr(_local, 'conn') or _local.conn is None:
        _local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


def init_db():
    """创建表结构（幂等）。"""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT UNIQUE NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL,
            duration_seconds REAL NOT NULL,
            total_tested INTEGER DEFAULT 0,
            total_passed INTEGER DEFAULT 0,
            total_failed INTEGER DEFAULT 0,
            pass_rate REAL DEFAULT 0,
            unique_channels_passed INTEGER DEFAULT 0,
            unique_channels_total INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS run_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            channel TEXT NOT NULL,
            url TEXT NOT NULL,
            resolution TEXT,
            bandwidth_MBps REAL,
            connection_latency_ms REAL,
            quality_score REAL,
            output_updated_at TEXT,
            codec TEXT,
            is_h265 BOOLEAN DEFAULT 0,
            sample_seconds REAL,
            passed BOOLEAN DEFAULT 0,
            reason TEXT,
            cost_seconds REAL,
            FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_results_run_id ON run_results(run_id);
        CREATE INDEX IF NOT EXISTS idx_results_channel ON run_results(channel);

        CREATE TABLE IF NOT EXISTS config_data (
            key TEXT PRIMARY KEY,
            content TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS run_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            ts TEXT NOT NULL,
            level TEXT DEFAULT 'INFO',
            message TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_logs_run_id ON run_logs(run_id);

        CREATE TABLE IF NOT EXISTS run_progress (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            running BOOLEAN DEFAULT 0,
            started_at TEXT,
            total INTEGER DEFAULT 0,
            processed INTEGER DEFAULT 0,
            passed INTEGER DEFAULT 0,
            failed INTEGER DEFAULT 0,
            elapsed REAL DEFAULT 0,
            source TEXT DEFAULT '',
            updated_at TEXT
        );
        INSERT OR IGNORE INTO run_progress (id) VALUES (1);

        CREATE TABLE IF NOT EXISTS scheduler_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            running BOOLEAN DEFAULT 0,
            next_run TEXT,
            owner TEXT DEFAULT '',
            updated_at TEXT
        );
        INSERT OR IGNORE INTO scheduler_state (id) VALUES (1);

        CREATE TABLE IF NOT EXISTS scan_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id TEXT UNIQUE NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT DEFAULT 'running',
            trigger_source TEXT DEFAULT 'web',
            platforms_used TEXT,
            total_raw INTEGER DEFAULT 0,
            total_deduped INTEGER DEFAULT 0,
            total_fast_pass INTEGER DEFAULT 0,
            total_deep_pass INTEGER DEFAULT 0,
            duration_seconds REAL DEFAULT 0,
            error TEXT
        );

        CREATE TABLE IF NOT EXISTS scan_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id TEXT NOT NULL,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            category TEXT,
            province TEXT,
            city TEXT,
            source_ip TEXT,
            resolution TEXT,
            codec TEXT,
            delay REAL,
            bandwidth REAL,
            stability INTEGER DEFAULT 0,
            tested_in_run TEXT,
            test_passed BOOLEAN,
            FOREIGN KEY (scan_id) REFERENCES scan_runs(scan_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_scan_results_scan_id ON scan_results(scan_id);
        CREATE INDEX IF NOT EXISTS idx_scan_results_category ON scan_results(category);
        CREATE INDEX IF NOT EXISTS idx_scan_results_province ON scan_results(province);

        CREATE TABLE IF NOT EXISTS scan_progress (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            running BOOLEAN DEFAULT 0,
            started_at TEXT,
            phase TEXT DEFAULT '',
            total INTEGER DEFAULT 0,
            processed INTEGER DEFAULT 0,
            percent REAL DEFAULT 0,
            message TEXT DEFAULT '',
            updated_at TEXT
        );
        INSERT OR IGNORE INTO scan_progress (id) VALUES (1);

        CREATE TABLE IF NOT EXISTS scan_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seq INTEGER NOT NULL,
            time TEXT NOT NULL,
            msg TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_scan_logs_seq ON scan_logs(seq);
    """)
    _ensure_run_results_columns(conn)
    conn.commit()
    _init_default_data()


def _ensure_run_results_columns(conn):
    """为旧数据库补齐新增结果字段。"""
    rows = conn.execute("PRAGMA table_info(run_results)").fetchall()
    existing = {row['name'] for row in rows}
    columns = {
        'connection_latency_ms': 'REAL',
        'quality_score': 'REAL',
        'output_updated_at': 'TEXT',
    }
    for name, col_type in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE run_results ADD COLUMN {name} {col_type}")


def insert_run(run_data):
    """将一轮测试结果写入数据库，同时清理超出上限的旧记录。"""
    conn = _get_conn()
    summary = run_data.get('summary', {})

    conn.execute(
        """INSERT OR REPLACE INTO runs
           (run_id, started_at, finished_at, duration_seconds,
            total_tested, total_passed, total_failed, pass_rate,
            unique_channels_passed, unique_channels_total)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            run_data['run_id'],
            run_data.get('started_at', ''),
            run_data.get('finished_at', ''),
            run_data.get('duration_seconds', 0),
            summary.get('total_tested', 0),
            summary.get('total_passed', 0),
            summary.get('total_failed', 0),
            summary.get('pass_rate', 0),
            summary.get('unique_channels_passed', 0),
            summary.get('unique_channels_total', 0),
        )
    )

    results = run_data.get('results', [])
    if results:
        conn.executemany(
            """INSERT INTO run_results
               (run_id, channel, url, resolution, bandwidth_MBps,
                connection_latency_ms, quality_score, output_updated_at,
                codec, is_h265, sample_seconds, passed, reason, cost_seconds)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    run_data['run_id'],
                    r.get('channel', ''),
                    r.get('url', ''),
                    r.get('resolution', ''),
                    r.get('bandwidth_MBps', 0),
                    r.get('connection_latency_ms'),
                    r.get('quality_score', 0),
                    r.get('output_updated_at', ''),
                    r.get('codec', ''),
                    r.get('is_h265', False),
                    r.get('sample_seconds', 0),
                    r.get('passed', False),
                    r.get('reason', ''),
                    r.get('cost_seconds', 0),
                )
                for r in results
            ]
        )

    conn.commit()
    _cleanup_old_runs(conn)


def _cleanup_old_runs(conn):
    """保留最近 MAX_RUNS 轮，删除多余的。"""
    rows = conn.execute(
        "SELECT run_id FROM runs ORDER BY id DESC LIMIT -1 OFFSET ?",
        (MAX_RUNS,)
    ).fetchall()
    for row in rows:
        conn.execute("DELETE FROM run_results WHERE run_id = ?", (row['run_id'],))
        conn.execute("DELETE FROM runs WHERE run_id = ?", (row['run_id'],))
    if rows:
        conn.commit()


def get_latest_run():
    """获取最近一轮测试的完整信息（含结果）。"""
    conn = _get_conn()
    run = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    if not run:
        return None

    results = conn.execute(
        "SELECT * FROM run_results WHERE run_id = ? ORDER BY id",
        (run['run_id'],)
    ).fetchall()

    return {
        'run_id': run['run_id'],
        'started_at': run['started_at'],
        'finished_at': run['finished_at'],
        'duration_seconds': run['duration_seconds'],
        'summary': {
            'total_tested': run['total_tested'],
            'total_passed': run['total_passed'],
            'total_failed': run['total_failed'],
            'pass_rate': run['pass_rate'],
            'unique_channels_passed': run['unique_channels_passed'],
            'unique_channels_total': run['unique_channels_total'],
        },
        'results': [dict(r) for r in results],
    }


def get_latest_passed_results():
    """获取最近一轮通过的频道列表（用于生成 result.txt/m3u）。"""
    conn = _get_conn()
    run = conn.execute("SELECT run_id FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    if not run:
        return []
    results = conn.execute(
        """SELECT channel, url, bandwidth_MBps, connection_latency_ms, quality_score, output_updated_at
           FROM run_results
           WHERE run_id = ? AND passed = 1
           ORDER BY channel,
                    COALESCE(quality_score, 0) DESC,
                    COALESCE(bandwidth_MBps, 0) DESC,
                    COALESCE(connection_latency_ms, 999999999) ASC,
                    id""",
        (run['run_id'],)
    ).fetchall()
    return [dict(r) for r in results]


def get_run_history(limit=50, start_date=None, end_date=None):
    """获取历史轮次列表（不含详细结果）。支持日期范围筛选。"""
    conn = _get_conn()
    params = []
    where = ""
    if start_date:
        where += " AND finished_at >= ?"
        params.append(start_date + " 00:00:00")
    if end_date:
        # end_date 当天包含在内，取次日 00:00:00 作为 <
        try:
            from datetime import datetime, timedelta
            d = datetime.strptime(end_date, "%Y-%m-%d")
            next_day = (d + timedelta(days=1)).strftime("%Y-%m-%d") + " 00:00:00"
            where += " AND finished_at < ?"
            params.append(next_day)
        except ValueError:
            pass
    params.append(limit)
    rows = conn.execute(
        f"SELECT * FROM runs WHERE 1=1{where} ORDER BY id DESC LIMIT ?",
        params
    ).fetchall()
    runs = []
    for r in rows:
        runs.append({
            'run_id': r['run_id'],
            'started_at': r['started_at'],
            'finished_at': r['finished_at'],
            'duration_seconds': r['duration_seconds'],
            'summary': {
                'total_tested': r['total_tested'],
                'total_passed': r['total_passed'],
                'total_failed': r['total_failed'],
                'pass_rate': r['pass_rate'],
                'unique_channels_passed': r['unique_channels_passed'],
                'unique_channels_total': r['unique_channels_total'],
            }
        })
    return runs


def get_run_detail(run_id):
    """获取指定轮次的完整信息（含结果）。"""
    conn = _get_conn()
    run = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if not run:
        return None
    results = conn.execute(
        """SELECT * FROM run_results WHERE run_id = ?
           ORDER BY channel,
                    passed DESC,
                    COALESCE(quality_score, 0) DESC,
                    COALESCE(bandwidth_MBps, 0) DESC,
                    COALESCE(connection_latency_ms, 999999999) ASC,
                    id""",
        (run_id,)
    ).fetchall()
    return {
        'run_id': run['run_id'],
        'started_at': run['started_at'],
        'finished_at': run['finished_at'],
        'duration_seconds': run['duration_seconds'],
        'summary': {
            'total_tested': run['total_tested'],
            'total_passed': run['total_passed'],
            'total_failed': run['total_failed'],
            'pass_rate': run['pass_rate'],
            'unique_channels_passed': run['unique_channels_passed'],
            'unique_channels_total': run['unique_channels_total'],
        },
        'results': [dict(r) for r in results],
    }


def get_channel_summary(run_id):
    """按频道聚合某轮测试结果。"""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT channel,
                  COUNT(*) as total,
                  SUM(CASE WHEN passed THEN 1 ELSE 0 END) as passed
           FROM run_results WHERE run_id = ?
           GROUP BY channel ORDER BY channel""",
        (run_id,)
    ).fetchall()

    detail_rows = conn.execute(
        """SELECT * FROM run_results WHERE run_id = ?
           ORDER BY channel,
                    passed DESC,
                    COALESCE(quality_score, 0) DESC,
                    COALESCE(bandwidth_MBps, 0) DESC,
                    COALESCE(connection_latency_ms, 999999999) ASC,
                    id""",
        (run_id,)
    ).fetchall()

    details_by_channel = {}
    for r in detail_rows:
        ch = r['channel']
        if ch not in details_by_channel:
            details_by_channel[ch] = []
        details_by_channel[ch].append(dict(r))

    summary = {}
    for r in rows:
        ch = r['channel']
        summary[ch] = {
            'total': r['total'],
            'passed': r['passed'],
            'urls': details_by_channel.get(ch, []),
        }
    return summary


def get_codec_stats(run_id):
    """统计编码格式分布。"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT codec, COUNT(*) as cnt FROM run_results WHERE run_id = ? GROUP BY codec",
        (run_id,)
    ).fetchall()
    stats = {}
    for r in rows:
        codec = r['codec'] or ''
        if codec in ('hevc', 'h265'):
            label = 'H.265/HEVC'
        elif codec in ('h264', 'avc'):
            label = 'H.264/AVC'
        elif codec:
            label = codec.upper()
        else:
            label = '未知'
        stats[label] = stats.get(label, 0) + r['cnt']
    return stats


def delete_run(run_id):
    """删除指定轮次及其所有结果。"""
    conn = _get_conn()
    conn.execute("DELETE FROM run_results WHERE run_id = ?", (run_id,))
    conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
    conn.commit()


def _looks_corrupt_text(text):
    """判断配置文本是否明显混入了二进制/损坏字节。"""
    return '\x00' in text or text.count('\ufffd') >= 3


def _default_config_data(key):
    if key == 'alias':
        return DEFAULT_ALIAS
    if key == 'demo':
        return DEFAULT_DEMO
    return None


def _decode_config_content(key, raw):
    """兼容读取历史库中非 UTF-8 或已损坏的配置文本。"""
    if raw is None:
        return ''
    if isinstance(raw, str):
        return raw
    if isinstance(raw, memoryview):
        raw = raw.tobytes()
    if not isinstance(raw, (bytes, bytearray)):
        return str(raw)

    data = bytes(raw)
    for encoding in ('utf-8-sig', 'utf-8', 'gb18030', 'cp936'):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue

    decoded = data.decode('utf-8', errors='replace')
    default_content = _default_config_data(key)
    if default_content is not None and _looks_corrupt_text(decoded):
        return default_content
    return decoded


def get_config_data(key):
    """获取配置数据内容（alias / demo / subscribe）。"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT CAST(content AS BLOB) AS content FROM config_data WHERE key = ?",
        (key,)
    ).fetchone()
    return _decode_config_content(key, row['content']) if row else ''


def set_config_data(key, content):
    """保存配置数据内容。"""
    conn = _get_conn()
    now = now_str()
    conn.execute(
        "INSERT OR REPLACE INTO config_data (key, content, updated_at) VALUES (?, ?, ?)",
        (key, content, now)
    )
    conn.commit()


def get_config(defaults=None):
    """从数据库读取系统配置，合并默认值。返回 dict。"""
    defaults = defaults or {}
    cfg = dict(defaults)
    raw = get_config_data(CONFIG_DATA)
    if raw:
        try:
            saved = json.loads(raw)
            for key, value in saved.items():
                if not key.startswith('#') and key in cfg:
                    cfg[key] = value
        except (json.JSONDecodeError, OSError):
            pass
    return cfg


def save_config(cfg):
    """保存系统配置到数据库。"""
    set_config_data(CONFIG_DATA, json.dumps(cfg, ensure_ascii=False, indent=4))


def migrate_config_from_file(filepath='config.json', defaults=None):
    """将 config.json 迁移到数据库（仅在数据库中无配置时执行）。"""
    defaults = defaults or {}
    conn = _get_conn()
    existing = conn.execute("SELECT 1 FROM config_data WHERE key = ?", (CONFIG_DATA,)).fetchone()
    if existing:
        return False  # 数据库已有配置，跳过
    if not os.path.exists(filepath):
        return False
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            file_cfg = json.load(f)
        cfg = dict(defaults)
        for key, value in file_cfg.items():
            if not key.startswith('#') and key in cfg:
                cfg[key] = value
        save_config(cfg)
        # 备份原文件
        bak_path = filepath + '.bak'
        try:
            os.rename(filepath, bak_path)
        except OSError:
            pass
        return True
    except (json.JSONDecodeError, OSError):
        return False


def _init_default_data():
    """首次启动时写入默认配置数据（已存在则跳过）。"""
    conn = _get_conn()
    defaults = {
        'demo': DEFAULT_DEMO,
        'alias': DEFAULT_ALIAS,
        'subscribe': '',
    }
    now = now_str()
    for key, content in defaults.items():
        existing = conn.execute("SELECT 1 FROM config_data WHERE key = ?", (key,)).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO config_data (key, content, updated_at) VALUES (?, ?, ?)",
                (key, content, now)
            )
    conn.commit()


def clear_run_progress():
    """清空运行进度（运行结束或新运行开始时调用）。"""
    conn = _get_conn()
    now = now_str()
    conn.execute(
        """UPDATE run_progress SET
           running=0, started_at=NULL, total=0, processed=0,
           passed=0, failed=0, elapsed=0, source='', updated_at=?
           WHERE id=1""",
        (now,)
    )
    conn.commit()


def update_run_progress(total, processed, passed, failed, elapsed, source=''):
    """更新运行进度（测试进行中由进度回调调用）。"""
    conn = _get_conn()
    now = now_str()
    conn.execute(
        """UPDATE run_progress SET
           running=1, total=?, processed=?, passed=?, failed=?,
           elapsed=?, source=?, updated_at=?
           WHERE id=1""",
        (total, processed, passed, failed, elapsed, source, now)
    )
    conn.commit()


def get_run_progress():
    """读取当前运行进度。返回 dict 或 None。"""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM run_progress WHERE id=1").fetchone()
    if not row:
        return None
    return {
        'running': bool(row['running']),
        'started_at': row['started_at'],
        'total': row['total'],
        'processed': row['processed'],
        'passed': row['passed'],
        'failed': row['failed'],
        'elapsed': row['elapsed'],
        'source': row['source'],
    }


def update_scheduler_state(running, next_run=None, owner=''):
    """更新后台调度器状态，供多进程 Web 请求读取。"""
    conn = _get_conn()
    now = now_str()
    conn.execute(
        """UPDATE scheduler_state SET
           running=?, next_run=?, owner=?, updated_at=?
           WHERE id=1""",
        (1 if running else 0, next_run or None, owner or '', now)
    )
    conn.commit()


def clear_scheduler_state():
    """清空后台调度器状态。"""
    update_scheduler_state(False, None, '')


def get_scheduler_state():
    """读取后台调度器状态。返回 dict 或 None。"""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM scheduler_state WHERE id=1").fetchone()
    if not row:
        return None
    return {
        'running': bool(row['running']),
        'next_run': row['next_run'],
        'owner': row['owner'],
        'updated_at': row['updated_at'],
    }


def insert_log(run_id, level, message):
    """写入一条日志到数据库。线程安全，每个线程独立连接。"""
    conn = _get_conn()
    now = now_str()
    conn.execute(
        "INSERT INTO run_logs (run_id, ts, level, message) VALUES (?, ?, ?, ?)",
        (run_id, now, level, message)
    )
    conn.commit()


def get_run_logs(run_id, limit=None):
    """获取指定轮次的日志列表。"""
    conn = _get_conn()
    total = conn.execute(
        "SELECT COUNT(*) AS cnt FROM run_logs WHERE run_id = ?",
        (run_id,)
    ).fetchone()['cnt']

    if limit is None:
        rows = conn.execute(
            "SELECT ts, level, message FROM run_logs WHERE run_id = ? ORDER BY id",
            (run_id,)
        ).fetchall()
        effective_limit = total
    else:
        try:
            effective_limit = int(limit)
        except (TypeError, ValueError):
            effective_limit = 0

        if effective_limit <= 0:
            rows = conn.execute(
                "SELECT ts, level, message FROM run_logs WHERE run_id = ? ORDER BY id",
                (run_id,)
            ).fetchall()
            effective_limit = total
        else:
            rows = conn.execute(
                "SELECT ts, level, message FROM run_logs WHERE run_id = ? ORDER BY id LIMIT ?",
                (run_id, effective_limit)
            ).fetchall()

    items = [dict(r) for r in rows]
    return {
        'total': total,
        'limit': effective_limit,
        'truncated': total > len(items),
        'logs': items,
    }


def migrate_from_json(json_path='output/history.json'):
    """将旧 history.json 数据迁移到 SQLite，迁移后重命名为 .bak。"""
    if not os.path.exists(json_path):
        return 0
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return 0

    runs = data.get('runs', [])
    if not runs:
        return 0

    conn = _get_conn()
    migrated = 0
    for run_data in runs:
        run_id = run_data.get('run_id', '')
        if not run_id:
            continue
        existing = conn.execute(
            "SELECT 1 FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if existing:
            continue

        insert_run(run_data)
        migrated += 1

    if migrated > 0:
        bak_path = json_path + '.bak'
        try:
            os.rename(json_path, bak_path)
        except OSError:
            pass

    return migrated


# ==================== 扫描模块 CRUD ====================

MAX_SCAN_RUNS = 50


def insert_scan_run(scan_data):
    """写入一条扫描记录。"""
    conn = _get_conn()
    conn.execute(
        """INSERT OR REPLACE INTO scan_runs
           (scan_id, started_at, finished_at, status, trigger_source,
            platforms_used, total_raw, total_deduped, total_fast_pass,
            total_deep_pass, duration_seconds, error)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            scan_data['scan_id'],
            scan_data.get('started_at', ''),
            scan_data.get('finished_at', ''),
            scan_data.get('status', 'running'),
            scan_data.get('trigger_source', 'web'),
            scan_data.get('platforms_used', ''),
            scan_data.get('total_raw', 0),
            scan_data.get('total_deduped', 0),
            scan_data.get('total_fast_pass', 0),
            scan_data.get('total_deep_pass', 0),
            scan_data.get('duration_seconds', 0),
            scan_data.get('error', ''),
        )
    )
    conn.commit()
    _cleanup_old_scan_runs(conn)


def update_scan_run(scan_id, **kwargs):
    """更新扫描记录的指定字段。"""
    if not kwargs:
        return
    conn = _get_conn()
    sets = ', '.join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [scan_id]
    conn.execute(f"UPDATE scan_runs SET {sets} WHERE scan_id = ?", vals)
    conn.commit()


def insert_scan_results(scan_id, channels):
    """批量写入扫描结果。channels 为 dict 列表。"""
    conn = _get_conn()
    conn.executemany(
        """INSERT INTO scan_results
           (scan_id, name, url, category, province, city, source_ip,
            resolution, codec, delay, bandwidth, stability)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                scan_id,
                ch.get('name', ''),
                ch.get('url', ''),
                ch.get('category', ''),
                ch.get('province', ''),
                ch.get('city', ''),
                ch.get('source_ip', ''),
                ch.get('resolution', ''),
                ch.get('codec', ''),
                ch.get('delay'),
                ch.get('bandwidth'),
                ch.get('stability', 0),
            )
            for ch in channels
        ]
    )
    conn.commit()


def update_scan_result_stability(scan_id, url, stability, delay=None,
                                  bandwidth=None, resolution=None, codec=None):
    """更新单条扫描结果的检测指标。"""
    conn = _get_conn()
    sets = ["stability = ?"]
    vals = [stability]
    if delay is not None:
        sets.append("delay = ?")
        vals.append(delay)
    if bandwidth is not None:
        sets.append("bandwidth = ?")
        vals.append(bandwidth)
    if resolution is not None:
        sets.append("resolution = ?")
        vals.append(resolution)
    if codec is not None:
        sets.append("codec = ?")
        vals.append(codec)
    vals.extend([scan_id, url])
    conn.execute(
        f"UPDATE scan_results SET {', '.join(sets)} WHERE scan_id = ? AND url = ?",
        vals
    )
    conn.commit()


def delete_scan_results_by_urls(scan_id, urls):
    """删除扫描结果中指定 URL 的条目。"""
    conn = _get_conn()
    conn.executemany(
        "DELETE FROM scan_results WHERE scan_id = ? AND url = ?",
        [(scan_id, u) for u in urls]
    )
    conn.commit()


def get_scan_results(scan_id=None, page=1, size=50, category=None,
                     province=None, search=None):
    """分页查询扫描结果。返回 (total, items)。"""
    conn = _get_conn()
    where = ["1=1"]
    params = []
    if scan_id:
        where.append("scan_id = ?")
        params.append(scan_id)
    if category:
        where.append("category = ?")
        params.append(category)
    if province:
        where.append("province = ?")
        params.append(province)
    if search:
        where.append("name LIKE ?")
        params.append(f"%{search}%")
    where_sql = ' AND '.join(where)

    total = conn.execute(
        f"SELECT COUNT(*) AS cnt FROM scan_results WHERE {where_sql}",
        params
    ).fetchone()['cnt']

    offset = (page - 1) * size
    rows = conn.execute(
        f"""SELECT * FROM scan_results WHERE {where_sql}
            ORDER BY stability DESC, bandwidth DESC, id
            LIMIT ? OFFSET ?""",
        params + [size, offset]
    ).fetchall()
    return total, [dict(r) for r in rows]


def get_scan_results_for_feed(scan_id, channel_names=None):
    """获取用于送入测速的扫描结果。channel_names 为 None 时取全部。"""
    conn = _get_conn()
    if channel_names:
        placeholders = ','.join('?' * len(channel_names))
        rows = conn.execute(
            f"""SELECT name, url, category, source_ip FROM scan_results
                WHERE scan_id = ? AND stability > 0
                  AND name IN ({placeholders})
                ORDER BY name, stability DESC, bandwidth DESC""",
            [scan_id] + list(channel_names)
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT name, url, category, source_ip FROM scan_results
               WHERE scan_id = ? AND stability > 0
               ORDER BY name, stability DESC, bandwidth DESC""",
            (scan_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def mark_scan_results_tested(scan_id, urls, run_id, passed=None):
    """标记扫描结果已参与测速。"""
    conn = _get_conn()
    if passed is not None:
        conn.executemany(
            "UPDATE scan_results SET tested_in_run = ?, test_passed = ? WHERE scan_id = ? AND url = ?",
            [(run_id, passed, scan_id, u) for u in urls]
        )
    else:
        conn.executemany(
            "UPDATE scan_results SET tested_in_run = ? WHERE scan_id = ? AND url = ?",
            [(run_id, scan_id, u) for u in urls]
        )
    conn.commit()


def get_scan_run(scan_id):
    """获取单条扫描记录。"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM scan_runs WHERE scan_id = ?", (scan_id,)
    ).fetchone()
    return dict(row) if row else None


def get_scan_history(limit=50):
    """获取扫描历史列表。"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM scan_runs ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_latest_scan_run():
    """获取最新一条扫描记录。"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM scan_runs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def delete_scan_run(scan_id):
    """删除扫描记录及其所有结果。"""
    conn = _get_conn()
    conn.execute("DELETE FROM scan_results WHERE scan_id = ?", (scan_id,))
    conn.execute("DELETE FROM scan_runs WHERE scan_id = ?", (scan_id,))
    conn.commit()


def _cleanup_old_scan_runs(conn):
    """保留最近 MAX_SCAN_RUNS 条扫描记录。"""
    rows = conn.execute(
        "SELECT scan_id FROM scan_runs ORDER BY id DESC LIMIT -1 OFFSET ?",
        (MAX_SCAN_RUNS,)
    ).fetchall()
    for row in rows:
        conn.execute("DELETE FROM scan_results WHERE scan_id = ?", (row['scan_id'],))
        conn.execute("DELETE FROM scan_runs WHERE scan_id = ?", (row['scan_id'],))
    if rows:
        conn.commit()


# --- scan_progress ---

def get_scan_progress():
    """读取扫描进度。"""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM scan_progress WHERE id = 1").fetchone()
    if not row:
        return {'running': False, 'phase': 'idle', 'total': 0,
                'processed': 0, 'percent': 0, 'message': ''}
    return dict(row)


def update_scan_progress(**kwargs):
    """更新扫描进度。"""
    if not kwargs:
        return
    kwargs['updated_at'] = now_str()
    conn = _get_conn()
    sets = ', '.join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values())
    conn.execute(f"UPDATE scan_progress SET {sets} WHERE id = 1", vals)
    conn.commit()


def clear_scan_progress():
    """重置扫描进度为空闲。"""
    update_scan_progress(
        running=False, started_at='', phase='idle',
        total=0, processed=0, percent=0, message='空闲'
    )


def insert_scan_log(seq, time_str, msg):
    """写入一条扫描日志到数据库。"""
    conn = _get_conn()
    conn.execute(
        "INSERT INTO scan_logs (seq, time, msg) VALUES (?, ?, ?)",
        (seq, time_str, msg)
    )
    conn.commit()


def get_scan_logs(after_seq=0, limit=300):
    """读取扫描日志，只返回 seq > after_seq 的行（增量拉取）。"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT seq, time, msg FROM scan_logs WHERE seq > ? ORDER BY seq ASC LIMIT ?",
        (after_seq, limit)
    ).fetchall()
    return [dict(r) for r in rows]


def clear_scan_logs():
    """清空扫描日志表（新扫描开始前调用）。"""
    conn = _get_conn()
    conn.execute("DELETE FROM scan_logs")
    conn.commit()


def get_scan_stats(scan_id=None):
    """获取扫描结果的统计信息（按分类、省份分布）。"""
    conn = _get_conn()
    where = "WHERE scan_id = ?" if scan_id else ""
    params = [scan_id] if scan_id else []

    cat_rows = conn.execute(
        f"SELECT category, COUNT(*) as cnt FROM scan_results {where} GROUP BY category ORDER BY cnt DESC",
        params
    ).fetchall()

    prov_rows = conn.execute(
        f"""SELECT CASE WHEN province = '' OR province IS NULL THEN '未知' ELSE province END as prov,
                   COUNT(*) as cnt
            FROM scan_results {where} GROUP BY prov ORDER BY cnt DESC""",
        params
    ).fetchall()

    return {
        'by_category': {r['category'] or '未分类': r['cnt'] for r in cat_rows},
        'by_province': {r['prov']: r['cnt'] for r in prov_rows},
    }

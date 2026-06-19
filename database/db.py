"""IPTV 测速结果 SQLite 数据库模块。"""
import json
import logging
import os
import shutil
import sqlite3
import threading
import time as _time
from collections import deque
from datetime import datetime, timedelta, timezone

logger = logging.getLogger('database')

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'iptv.db')
MAX_RUNS = 50
CONFIG_DATA = 'config'  # config_data 表中存储系统配置的 key
LOCAL_TZ = timezone(timedelta(hours=8))

# VACUUM 互斥锁：防止 VACUUM 期间其他连接写入导致数据库损坏
_vacuum_lock = threading.Lock()


def now_str():
    return datetime.now(LOCAL_TZ).strftime('%Y-%m-%d %H:%M:%S')


def timestamp_str(ts):
    return datetime.fromtimestamp(ts, LOCAL_TZ).strftime('%Y-%m-%d %H:%M:%S')


# ─── 日志批量写入 ───

class LogBatcher:
    """线程安全的日志批量写入器，减少 commit 次数。"""

    def __init__(self, flush_interval=3.0, max_size=200):
        self._buffer = deque()
        self._lock = threading.Lock()
        self._flush_interval = flush_interval
        self._max_size = max_size
        self._last_flush = _time.monotonic()
        self._timer = None
        self._active = False

    def add(self, table, row):
        """添加一行日志到缓冲区。table: 'run_logs'|'scan_logs'|'detection_logs'"""
        with self._lock:
            self._buffer.append((table, row))
            if len(self._buffer) >= self._max_size:
                self._do_flush()
                return
        # 定时刷新：如果距上次 flush 超过间隔，提交一次
        if _time.monotonic() - self._last_flush > self._flush_interval:
            self.flush()

    def flush(self):
        with self._lock:
            self._do_flush()

    def _do_flush(self):
        """调用时必须持有 self._lock。"""
        if not self._buffer:
            return
        items = list(self._buffer)
        self._buffer.clear()
        # 按表分组
        grouped = {}
        for table, row in items:
            grouped.setdefault(table, []).append(row)
        conn = _get_conn()
        for table, rows in grouped.items():
            if table == 'run_logs':
                conn.executemany(
                    "INSERT INTO run_logs (run_id, ts, level, message) VALUES (?, ?, ?, ?)",
                    rows
                )
            elif table == 'scan_logs':
                conn.executemany(
                    "INSERT INTO scan_logs (seq, time, msg) VALUES (?, ?, ?)",
                    rows
                )
            elif table == 'detection_logs':
                conn.executemany(
                    "INSERT INTO detection_logs (ts, level, message) VALUES (?, ?, ?)",
                    rows
                )
        conn.commit()
        self._last_flush = _time.monotonic()


# 模块级单例
_log_batcher = LogBatcher()


def flush_log_buffer():
    """手动刷新日志缓冲区，确保所有缓冲日志写入数据库。"""
    _log_batcher.flush()

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


def check_and_recover_db():
    """
    启动时检查数据库完整性。
    如果发现损坏，备份损坏文件并用空库替代。
    返回 True 表示数据库正常，False 表示已执行恢复。
    """
    if not os.path.exists(DB_PATH):
        return True

    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        result = conn.execute('PRAGMA integrity_check').fetchone()
        conn.close()
        if result and result[0] == 'ok':
            return True
    except sqlite3.DatabaseError as e:
        logger.error(f"[DB] 数据库完整性检查异常: {e}")

    # 数据库已损坏，执行恢复
    logger.warning("[DB] 数据库已损坏，开始自动恢复...")
    try:
        # 备份损坏文件
        backup_path = DB_PATH + f'.corrupted.{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        shutil.copy2(DB_PATH, backup_path)
        logger.info(f"[DB] 已备份损坏数据库到: {backup_path}")

        # 尝试恢复数据
        recovered = _recover_database(backup_path, DB_PATH)
        if recovered:
            logger.info(f"[DB] 数据恢复成功")
        else:
            logger.warning("[DB] 数据恢复失败，已用空库替代")
        return recovered
    except Exception as e:
        logger.exception(f"[DB] 数据库恢复过程异常: {e}")
        # 最后手段：删除损坏文件，让 init_db 重建
        try:
            os.remove(DB_PATH)
            for suffix in ('-wal', '-shm'):
                p = DB_PATH + suffix
                if os.path.exists(p):
                    os.remove(p)
        except OSError:
            pass
        return False


def _recover_database(corrupted_path, target_path):
    """
    尝试从损坏的数据库中恢复数据到新数据库。
    返回 True 表示恢复成功。
    """
    try:
        old_conn = sqlite3.connect(corrupted_path)
        old_conn.row_factory = sqlite3.Row

        # 获取表结构和索引
        schemas = [r[0] for r in old_conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL"
        ).fetchall()]
        indexes = [r[0] for r in old_conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
        ).fetchall()]

        # 创建新数据库
        new_path = target_path + '.recovering'
        if os.path.exists(new_path):
            os.remove(new_path)
        new_conn = sqlite3.connect(new_path)
        new_conn.execute('PRAGMA journal_mode=WAL')
        new_conn.execute('PRAGMA foreign_keys=OFF')

        # 建表
        for sql in schemas:
            try:
                new_conn.execute(sql)
            except sqlite3.OperationalError:
                pass  # sqlite_sequence 等系统表

        # 逐表恢复数据
        tables = [r[0] for r in old_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        total = 0
        for table in tables:
            if table == 'sqlite_sequence':
                continue
            try:
                rows = old_conn.execute(f'SELECT * FROM [{table}]').fetchall()
                if not rows:
                    continue
                cols = [d[0] for d in old_conn.execute(
                    f'SELECT * FROM [{table}] LIMIT 0'
                ).description]
                placeholders = ','.join(['?' for _ in cols])
                col_names = ','.join([f'[{c}]' for c in cols])
                sql = f'INSERT OR IGNORE INTO [{table}] ({col_names}) VALUES ({placeholders})'
                new_conn.executemany(sql, [tuple(r) for r in rows])
                new_conn.commit()
                total += len(rows)
                logger.info(f"[DB] 恢复表 {table}: {len(rows)} 行")
            except sqlite3.DatabaseError as e:
                logger.warning(f"[DB] 恢复表 {table} 失败: {e}")

        # 创建索引
        for sql in indexes:
            try:
                new_conn.execute(sql)
            except sqlite3.OperationalError:
                pass

        new_conn.commit()
        new_conn.close()
        old_conn.close()

        # 验证新数据库
        check_conn = sqlite3.connect(new_path)
        result = check_conn.execute('PRAGMA integrity_check').fetchone()
        check_conn.close()

        if result and result[0] == 'ok':
            # 替换目标文件
            for suffix in ('-wal', '-shm'):
                p = target_path + suffix
                if os.path.exists(p):
                    os.remove(p)
            os.replace(new_path, target_path)
            logger.info(f"[DB] 数据恢复完成，共恢复 {total} 行")
            return True
        else:
            logger.error("[DB] 恢复后的数据库未通过完整性检查")
            os.remove(new_path)
            return False

    except Exception as e:
        logger.exception(f"[DB] _recover_database 异常: {e}")
        return False


def _get_conn():
    """每个线程获取独立的数据库连接。检测到数据库损坏时自动重连恢复后的库。"""
    if not hasattr(_local, 'conn') or _local.conn is None:
        _local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
        # 多线程并发写（深度检测/检测循环/Flask 请求共用 DB）时，
        # 遇到锁等待最多 5 秒而非立即抛 database is locked。
        _local.conn.execute("PRAGMA busy_timeout=5000")
    return _local.conn


def _reset_thread_conn():
    """重置当前线程的数据库连接（损坏恢复后调用）。"""
    if hasattr(_local, 'conn') and _local.conn is not None:
        try:
            _local.conn.close()
        except Exception:
            pass
        _local.conn = None


def init_db():
    """检查数据库完整性，必要时恢复，然后创建表结构（幂等）。"""
    # 启动时完整性检查，损坏则自动恢复
    check_and_recover_db()
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
            source_url TEXT DEFAULT '',
            FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_results_run_id ON run_results(run_id);
        CREATE INDEX IF NOT EXISTS idx_results_channel ON run_results(channel);
        CREATE INDEX IF NOT EXISTS idx_results_run_passed ON run_results(run_id, passed);
        CREATE INDEX IF NOT EXISTS idx_results_quality ON run_results(quality_score);
        CREATE INDEX IF NOT EXISTS idx_runs_finished_at ON runs(finished_at);

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
            platform TEXT DEFAULT '',
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
        CREATE INDEX IF NOT EXISTS idx_scan_results_name ON scan_results(name);
        CREATE INDEX IF NOT EXISTS idx_scan_results_scan_url ON scan_results(scan_id, url);
        CREATE INDEX IF NOT EXISTS idx_scan_runs_started ON scan_runs(started_at);

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

        CREATE TABLE IF NOT EXISTS persistent_scan_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            category TEXT,
            province TEXT,
            city TEXT,
            source_ip TEXT,
            platform TEXT,
            resolution TEXT,
            codec TEXT,
            delay REAL,
            bandwidth REAL,
            stability INTEGER DEFAULT 0,
            quality_status TEXT DEFAULT 'pending',
            consecutive_failures INTEGER DEFAULT 0,
            last_checked_at TEXT,
            first_seen_at TEXT NOT NULL,
            last_updated_at TEXT NOT NULL,
            validated INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_psr_src ON persistent_scan_results(source_ip);
        CREATE INDEX IF NOT EXISTS idx_psr_quality ON persistent_scan_results(quality_status);
        CREATE INDEX IF NOT EXISTS idx_psr_platform ON persistent_scan_results(platform);
        CREATE INDEX IF NOT EXISTS idx_psr_validated ON persistent_scan_results(validated);
        CREATE INDEX IF NOT EXISTS idx_psr_name ON persistent_scan_results(name);

        CREATE TABLE IF NOT EXISTS detection_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            level TEXT DEFAULT 'INFO',
            message TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_detection_logs_ts ON detection_logs(ts);

        CREATE TABLE IF NOT EXISTS detection_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cycle_id TEXT NOT NULL UNIQUE,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            trigger_source TEXT DEFAULT 'auto',
            total_checked INTEGER DEFAULT 0,
            ok_count INTEGER DEFAULT 0,
            failed_count INTEGER DEFAULT 0,
            deleted_count INTEGER DEFAULT 0,
            duration_seconds REAL DEFAULT 0,
            error TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_det_runs_started ON detection_runs(started_at);

        CREATE TABLE IF NOT EXISTS detection_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cycle_id TEXT NOT NULL,
            url TEXT NOT NULL,
            name TEXT,
            check_ok INTEGER DEFAULT 0,
            http_status INTEGER DEFAULT 0,
            response_time_ms REAL DEFAULT 0,
            response_size_bytes INTEGER DEFAULT 0,
            consecutive_failures INTEGER DEFAULT 0,
            quality_status TEXT DEFAULT 'pending',
            FOREIGN KEY (cycle_id) REFERENCES detection_runs(cycle_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_det_results_cycle ON detection_results(cycle_id);
        CREATE INDEX IF NOT EXISTS idx_det_results_cycle_ok ON detection_results(cycle_id, check_ok);
    """)
    _ensure_run_results_columns(conn)
    _ensure_scan_results_columns(conn)
    conn.commit()
    _init_default_data()
    # 启动时兜底清理超期日志
    try:
        cleanup_old_run_logs(days=30)
    except Exception:
        pass
    # 启动时自动压缩过大的数据库
    try:
        auto_vacuum_if_needed()
    except Exception:
        pass


def _ensure_run_results_columns(conn):
    """为旧数据库补齐新增结果字段。"""
    rows = conn.execute("PRAGMA table_info(run_results)").fetchall()
    existing = {row['name'] for row in rows}
    columns = {
        'connection_latency_ms': 'REAL',
        'quality_score': 'REAL',
        'output_updated_at': 'TEXT',
        'source_url': 'TEXT DEFAULT \'\'',
    }
    for name, col_type in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE run_results ADD COLUMN {name} {col_type}")


def _ensure_scan_results_columns(conn):
    """为旧数据库补齐 scan_results 新增字段。"""
    rows = conn.execute("PRAGMA table_info(scan_results)").fetchall()
    existing = {row['name'] for row in rows}
    if 'platform' not in existing:
        conn.execute("ALTER TABLE scan_results ADD COLUMN platform TEXT DEFAULT ''")


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
                codec, is_h265, sample_seconds, passed, reason, cost_seconds, source_url)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    r.get('source_url', ''),
                )
                for r in results
            ]
        )

    conn.commit()
    _cleanup_old_runs(conn)


def _cleanup_old_runs(conn):
    """保留最近 MAX_RUNS 轮，删除多余的（含日志）。"""
    rows = conn.execute(
        "SELECT run_id FROM runs ORDER BY id DESC LIMIT -1 OFFSET ?",
        (MAX_RUNS,)
    ).fetchall()
    if not rows:
        return
    ids = [row['run_id'] for row in rows]
    placeholders = ','.join('?' * len(ids))
    conn.execute(f"DELETE FROM run_logs WHERE run_id IN ({placeholders})", ids)
    conn.execute(f"DELETE FROM run_results WHERE run_id IN ({placeholders})", ids)
    conn.execute(f"DELETE FROM runs WHERE run_id IN ({placeholders})", ids)
    conn.commit()


def cleanup_old_run_logs(days=30):
    """删除 N 天前的测速日志（兜底清理）。"""
    conn = _get_conn()
    cutoff = (datetime.now(LOCAL_TZ) - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
    deleted = conn.execute("DELETE FROM run_logs WHERE ts < ?", (cutoff,)).rowcount
    if deleted:
        conn.commit()
    return deleted


def vacuum_database():
    """执行 VACUUM 回收 SQLite 碎片空间，缩小数据库文件。加锁防止并发写入。"""
    with _vacuum_lock:
        conn = _get_conn()
        conn.execute("VACUUM")
        conn.commit()


# VACUUM 阈值：数据库文件超过此大小（字节）时自动触发
_VACUUM_THRESHOLD = 50 * 1024 * 1024  # 50 MB


def auto_vacuum_if_needed():
    """检查数据库文件大小，超过阈值则自动 VACUUM。"""
    try:
        db_size = os.path.getsize(DB_PATH)
        if db_size > _VACUUM_THRESHOLD:
            vacuum_database()
            return True
    except OSError:
        pass
    return False


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


def get_run_detail(run_id, page=None, size=50):
    """获取指定轮次的完整信息（含结果）。page 为 None 时返回全部结果。"""
    conn = _get_conn()
    run = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if not run:
        return None

    base = {
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
    }

    order = """ORDER BY channel,
                    passed DESC,
                    COALESCE(quality_score, 0) DESC,
                    COALESCE(bandwidth_MBps, 0) DESC,
                    COALESCE(connection_latency_ms, 999999999) ASC,
                    id"""

    if page is not None:
        total = conn.execute(
            "SELECT COUNT(*) AS cnt FROM run_results WHERE run_id = ?", (run_id,)
        ).fetchone()['cnt']
        offset = (page - 1) * size
        results = conn.execute(
            f"SELECT * FROM run_results WHERE run_id = ? {order} LIMIT ? OFFSET ?",
            (run_id, size, offset)
        ).fetchall()
        base['results'] = [dict(r) for r in results]
        base['total_results'] = total
        base['page'] = page
        base['page_size'] = size
    else:
        results = conn.execute(
            f"SELECT * FROM run_results WHERE run_id = ? {order}",
            (run_id,)
        ).fetchall()
        base['results'] = [dict(r) for r in results]

    return base


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


def get_channel_summary_with_source(run_id, page=None, size=20):
    """按频道聚合某轮测试结果，并关联数据来源平台。page 为 None 时返回全部频道。"""
    conn = _get_conn()

    order_detail = """ORDER BY channel,
                         passed DESC,
                         COALESCE(quality_score, 0) DESC,
                         COALESCE(bandwidth_MBps, 0) DESC,
                         COALESCE(connection_latency_ms, 999999999) ASC,
                         id"""

    if page is not None:
        # 计算总频道数
        total_channels = conn.execute(
            "SELECT COUNT(DISTINCT channel) as cnt FROM run_results WHERE run_id = ?",
            (run_id,)
        ).fetchone()['cnt']

        # 获取当前页的频道列表
        offset = (page - 1) * size
        channel_rows = conn.execute(
            """SELECT channel,
                      COUNT(*) as total,
                      SUM(CASE WHEN passed THEN 1 ELSE 0 END) as passed
               FROM run_results WHERE run_id = ?
               GROUP BY channel ORDER BY channel
               LIMIT ? OFFSET ?""",
            (run_id, size, offset)
        ).fetchall()

        channel_names = [r['channel'] for r in channel_rows]
        if not channel_names:
            return {'channels': {}, 'total_channels': total_channels, 'page': page, 'page_size': size}

        # 仅获取当前页频道的明细
        placeholders = ','.join(['?'] * len(channel_names))
        detail_rows = conn.execute(
            f"SELECT * FROM run_results WHERE run_id = ? AND channel IN ({placeholders}) {order_detail}",
            [run_id] + channel_names
        ).fetchall()
    else:
        # 原有行为：全部频道
        channel_rows = conn.execute(
            """SELECT channel,
                      COUNT(*) as total,
                      SUM(CASE WHEN passed THEN 1 ELSE 0 END) as passed
               FROM run_results WHERE run_id = ?
               GROUP BY channel ORDER BY channel""",
            (run_id,)
        ).fetchall()

        detail_rows = conn.execute(
            f"SELECT * FROM run_results WHERE run_id = ? {order_detail}",
            (run_id,)
        ).fetchall()
        total_channels = len(channel_rows)

    # 收集所有 URL，批量查询 persistent_scan_results 获取平台来源
    all_urls = [r['url'] for r in detail_rows]
    url_platform = {}
    if all_urls:
        batch_size = 500
        for i in range(0, len(all_urls), batch_size):
            batch = all_urls[i:i + batch_size]
            placeholders = ','.join(['?'] * len(batch))
            platform_rows = conn.execute(
                f"SELECT url, platform FROM persistent_scan_results WHERE url IN ({placeholders})",
                batch
            ).fetchall()
            for pr in platform_rows:
                url_platform[pr['url']] = pr['platform'] or '未知'

    # 按频道组装结果
    details_by_channel = {}
    sources_by_channel = {}
    for r in detail_rows:
        ch = r['channel']
        if ch not in details_by_channel:
            details_by_channel[ch] = []
            sources_by_channel[ch] = set()
        row_dict = dict(r)
        platform = url_platform.get(r['url'])
        row_dict['platform'] = platform or ''
        details_by_channel[ch].append(row_dict)
        if platform:
            sources_by_channel[ch].add(platform)

    summary = {}
    for r in channel_rows:
        ch = r['channel']
        sources = sorted(sources_by_channel.get(ch, set()))
        summary[ch] = {
            'total': r['total'],
            'passed': r['passed'],
            'sources': sources,
            'urls': details_by_channel.get(ch, []),
        }

    result = {'channels': summary, 'total_channels': total_channels}
    if page is not None:
        result['page'] = page
        result['page_size'] = size
    return result


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
    conn.execute("DELETE FROM run_logs WHERE run_id = ?", (run_id,))
    conn.execute("DELETE FROM run_results WHERE run_id = ?", (run_id,))
    conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
    conn.commit()


def compare_runs(run_id_a, run_id_b):
    """对比两轮测试，返回对比数据。run_id_a 为基准，run_id_b 为比较目标。"""
    conn = _get_conn()

    run_a = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id_a,)).fetchone()
    run_b = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id_b,)).fetchone()
    if not run_a or not run_b:
        return None

    def _run_summary(r):
        return {
            'run_id': r['run_id'],
            'finished_at': r['finished_at'],
            'duration_seconds': r['duration_seconds'],
            'total_tested': r['total_tested'],
            'total_passed': r['total_passed'],
            'total_failed': r['total_failed'],
            'pass_rate': r['pass_rate'],
            'unique_channels_passed': r['unique_channels_passed'],
            'unique_channels_total': r['unique_channels_total'],
        }

    def _best_per_channel(run_id):
        """每个频道取最佳结果：passed 优先，再按 quality_score 降序。"""
        rows = conn.execute(
            """SELECT channel, passed, bandwidth_MBps, connection_latency_ms,
                      quality_score, codec, url
               FROM run_results WHERE run_id = ?
               ORDER BY channel, passed DESC, COALESCE(quality_score, 0) DESC""",
            (run_id,)
        ).fetchall()
        best = {}
        for r in rows:
            ch = r['channel']
            if ch not in best:
                best[ch] = {
                    'passed': bool(r['passed']),
                    'bandwidth': r['bandwidth_MBps'],
                    'latency': r['connection_latency_ms'],
                    'score': r['quality_score'],
                    'codec': r['codec'],
                    'url': r['url'],
                }
        return best

    ch_a = _best_per_channel(run_id_a)
    ch_b = _best_per_channel(run_id_b)

    all_channels = sorted(set(ch_a) | set(ch_b))
    channels_a = set(ch_a)
    channels_b = set(ch_b)
    new_channels = channels_b - channels_a
    removed_channels = channels_a - channels_b

    comparisons = []
    improved = regressed = stable = 0

    for ch in all_channels:
        a = ch_a.get(ch)
        b = ch_b.get(ch)

        if ch in new_channels:
            status = 'new'
            improved += 0  # counted separately
        elif ch in removed_channels:
            status = 'removed'
        else:
            a_pass = a['passed'] if a else False
            b_pass = b['passed'] if b else False
            a_score = a['score'] or 0 if a else 0
            b_score = b['score'] or 0 if b else 0

            if (not a_pass and b_pass) or (a_score > 0 and b_score > a_score * 1.1):
                status = 'improved'
            elif (a_pass and not b_pass) or (a_score > 0 and b_score < a_score * 0.9):
                status = 'regressed'
            else:
                status = 'stable'

        if status == 'improved':
            improved += 1
        elif status == 'regressed':
            regressed += 1
        elif status == 'new':
            pass  # counted via len(new_channels)
        elif status == 'removed':
            pass  # counted via len(removed_channels)
        else:
            stable += 1

        comparisons.append({
            'channel': ch,
            'a_passed': a['passed'] if a else None,
            'b_passed': b['passed'] if b else None,
            'a_bandwidth': a['bandwidth'] if a else None,
            'b_bandwidth': b['bandwidth'] if b else None,
            'a_latency': a['latency'] if a else None,
            'b_latency': b['latency'] if b else None,
            'a_score': a['score'] if a else None,
            'b_score': b['score'] if b else None,
            'a_codec': a['codec'] if a else None,
            'b_codec': b['codec'] if b else None,
            'status': status,
        })

    # 排序：regressed → improved → new → removed → stable
    order = {'regressed': 0, 'improved': 1, 'new': 2, 'removed': 3, 'stable': 4}
    comparisons.sort(key=lambda x: (order.get(x['status'], 5), x['channel']))

    # 计算 delta
    ra = run_a['pass_rate'] or 0
    rb = run_b['pass_rate'] or 0

    def _avg(channel_map, key):
        vals = [v[key] for v in channel_map.values() if v[key] is not None]
        return sum(vals) / len(vals) if vals else 0

    avg_bw_a = _avg(ch_a, 'bandwidth')
    avg_bw_b = _avg(ch_b, 'bandwidth')
    avg_lat_a = _avg(ch_a, 'latency')
    avg_lat_b = _avg(ch_b, 'latency')

    return {
        'run_a': _run_summary(run_a),
        'run_b': _run_summary(run_b),
        'summary': {
            'channels_improved': improved,
            'channels_regressed': regressed,
            'new_channels': len(new_channels),
            'removed_channels': len(removed_channels),
            'pass_rate_delta': round(rb - ra, 2),
            'avg_bandwidth_delta': round(avg_bw_b - avg_bw_a, 3),
            'avg_latency_delta': round(avg_lat_b - avg_lat_a, 2),
        },
        'channels': comparisons,
    }


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
    """写入一条日志到数据库（缓冲批量提交）。"""
    _log_batcher.add('run_logs', (run_id, now_str(), level, message))


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
           (scan_id, name, url, category, province, city, source_ip, platform,
            resolution, codec, delay, bandwidth, stability)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                scan_id,
                ch.get('name', ''),
                ch.get('url', ''),
                ch.get('category', ''),
                ch.get('province', ''),
                ch.get('city', ''),
                ch.get('source_ip', ''),
                ch.get('platform', ''),
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
    if not rows:
        return
    ids = [row['scan_id'] for row in rows]
    placeholders = ','.join('?' * len(ids))
    conn.execute(f"DELETE FROM scan_results WHERE scan_id IN ({placeholders})", ids)
    conn.execute(f"DELETE FROM scan_runs WHERE scan_id IN ({placeholders})", ids)
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
    """写入一条扫描日志到数据库（缓冲批量提交）。"""
    _log_batcher.add('scan_logs', (seq, time_str, msg))


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


# ==================== 定期检测日志 (detection_logs) ====================


def insert_detection_log(level, message):
    """写入一条定期检测日志（缓冲批量提交）。"""
    _log_batcher.add('detection_logs', (now_str(), level, message))


def get_detection_logs(limit=200):
    """读取定期检测日志，返回最近 limit 条（按时间正序）。"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT ts, level, message FROM detection_logs ORDER BY id DESC LIMIT ?",
        (limit,)
    ).fetchall()
    return [dict(r) for r in reversed(rows)]


def clear_detection_logs(keep=500):
    """只保留最近 keep 条检测日志，删除更早的记录。"""
    conn = _get_conn()
    conn.execute(
        "DELETE FROM detection_logs WHERE id NOT IN "
        "(SELECT id FROM detection_logs ORDER BY id DESC LIMIT ?)",
        (keep,)
    )
    conn.commit()


# ==================== 定期检测轮次 (detection_runs / detection_results) ====================


def insert_detection_run(cycle_id, started_at, trigger_source='auto'):
    """创建一条检测轮次记录。"""
    conn = _get_conn()
    conn.execute(
        "INSERT INTO detection_runs (cycle_id, started_at, trigger_source) VALUES (?, ?, ?)",
        (cycle_id, started_at, trigger_source)
    )
    conn.commit()


def finish_detection_run(cycle_id, finished_at, total, ok, failed, deleted, duration, error=None):
    """更新检测轮次结束状态。"""
    conn = _get_conn()
    conn.execute(
        """UPDATE detection_runs
           SET finished_at=?, total_checked=?, ok_count=?,
               failed_count=?, deleted_count=?, duration_seconds=?, error=?
           WHERE cycle_id=?""",
        (finished_at, total, ok, failed, deleted, duration, error, cycle_id)
    )
    conn.commit()


def insert_detection_results(cycle_id, results_list):
    """批量插入某轮检测的每个 URL 结果明细。"""
    if not results_list:
        return
    conn = _get_conn()
    conn.executemany(
        """INSERT INTO detection_results
           (cycle_id, url, name, check_ok, http_status,
            response_time_ms, response_size_bytes,
            consecutive_failures, quality_status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                cycle_id,
                r['url'], r.get('name'), int(r['check_ok']),
                r.get('http_status', 0), r.get('response_time_ms', 0),
                r.get('response_size_bytes', 0), r.get('consecutive_failures', 0),
                r.get('quality_status', 'pending'),
            )
            for r in results_list
        ]
    )
    conn.commit()


def get_detection_runs(start=None, end=None, limit=100):
    """按时间范围查询检测轮次记录。"""
    conn = _get_conn()
    conditions = []
    params = []
    if start:
        conditions.append("started_at >= ?")
        params.append(start)
    if end:
        conditions.append("started_at <= ?")
        params.append(end)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)
    rows = conn.execute(
        f"""SELECT cycle_id, started_at, finished_at, trigger_source,
                   total_checked, ok_count, failed_count, deleted_count,
                   duration_seconds, error
            FROM detection_runs {where}
            ORDER BY started_at DESC LIMIT ?""",
        params
    ).fetchall()
    return [dict(r) for r in rows]


def get_detection_results(cycle_id, page=None, size=100):
    """查询某轮检测的所有 URL 结果明细。page 为 None 时返回全部结果。"""
    conn = _get_conn()

    if page is not None:
        total = conn.execute(
            "SELECT COUNT(*) AS cnt FROM detection_results WHERE cycle_id = ?",
            (cycle_id,)
        ).fetchone()['cnt']
        offset = (page - 1) * size
        rows = conn.execute(
            """SELECT url, name, check_ok, http_status,
                      response_time_ms, response_size_bytes,
                      consecutive_failures, quality_status
               FROM detection_results WHERE cycle_id = ? ORDER BY id
               LIMIT ? OFFSET ?""",
            (cycle_id, size, offset)
        ).fetchall()
        return {'total': total, 'items': [dict(r) for r in rows], 'page': page, 'page_size': size}
    else:
        rows = conn.execute(
            """SELECT url, name, check_ok, http_status,
                      response_time_ms, response_size_bytes,
                      consecutive_failures, quality_status
               FROM detection_results WHERE cycle_id = ? ORDER BY id""",
            (cycle_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def cleanup_old_detection_runs(keep=50):
    """只保留最近 keep 轮检测记录，删除更早的 runs + results。"""
    conn = _get_conn()
    old_ids = conn.execute(
        "SELECT cycle_id FROM detection_runs ORDER BY started_at DESC LIMIT -1 OFFSET ?",
        (keep,)
    ).fetchall()
    if old_ids:
        ids = [r['cycle_id'] for r in old_ids]
        placeholders = ','.join('?' * len(ids))
        conn.execute(f"DELETE FROM detection_results WHERE cycle_id IN ({placeholders})", ids)
        conn.execute(f"DELETE FROM detection_runs WHERE cycle_id IN ({placeholders})", ids)
        conn.commit()
    # 硬上限：detection_results 总行数超过 50000 时，删除最旧的 cycle
    total = conn.execute("SELECT COUNT(*) AS cnt FROM detection_results").fetchone()['cnt']
    if total > 50000:
        overflow = total - 50000
        old_cycles = conn.execute(
            """SELECT cycle_id FROM detection_runs ORDER BY started_at ASC"""
        ).fetchall()
        deleted = 0
        for row in old_cycles:
            if deleted >= overflow:
                break
            n = conn.execute(
                "SELECT COUNT(*) AS cnt FROM detection_results WHERE cycle_id = ?",
                (row['cycle_id'],)
            ).fetchone()['cnt']
            conn.execute("DELETE FROM detection_results WHERE cycle_id = ?", (row['cycle_id'],))
            conn.execute("DELETE FROM detection_runs WHERE cycle_id = ?", (row['cycle_id'],))
            deleted += n
        if deleted:
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


# ==================== 持久化扫描结果 (persistent_scan_results) ====================

def upsert_persistent_results(rows):
    """批量 UPSERT 到持久化结果表。URL 冲突时更新元数据并重置失败计数。"""
    if not rows:
        return
    conn = _get_conn()
    now = now_str()
    conn.executemany(
        """INSERT INTO persistent_scan_results
           (url, name, category, province, city, source_ip, platform,
            resolution, codec, delay, bandwidth, stability,
            quality_status, consecutive_failures, last_checked_at,
            first_seen_at, last_updated_at, validated)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, NULL, ?, ?, 0)
           ON CONFLICT(url) DO UPDATE SET
               name=excluded.name, category=excluded.category,
               province=excluded.province, city=excluded.city,
               source_ip=excluded.source_ip, platform=excluded.platform,
               resolution=excluded.resolution, codec=excluded.codec,
               delay=excluded.delay, bandwidth=excluded.bandwidth,
               stability=excluded.stability,
               quality_status=CASE WHEN excluded.stability > persistent_scan_results.stability
                                   THEN 'pending' ELSE persistent_scan_results.quality_status END,
               consecutive_failures=CASE WHEN excluded.stability > persistent_scan_results.stability
                                         THEN 0 ELSE persistent_scan_results.consecutive_failures END,
               last_checked_at=CASE WHEN excluded.stability > persistent_scan_results.stability
                                    THEN NULL ELSE persistent_scan_results.last_checked_at END,
               last_updated_at=excluded.last_updated_at,
               validated=CASE WHEN excluded.stability > persistent_scan_results.stability
                              THEN 0 ELSE persistent_scan_results.validated END""",
        [
            (
                r.get('url', ''), r.get('name', ''),
                r.get('category', ''), r.get('province', ''),
                r.get('city', ''), r.get('source_ip', ''),
                r.get('platform', ''),
                r.get('resolution', ''), r.get('codec', ''),
                r.get('delay'), r.get('bandwidth'),
                r.get('stability', 0),
                now, now,
            )
            for r in rows
        ]
    )
    conn.commit()


def get_persistent_details_by_ip(source_ip, page=None, size=50):
    """查询某个来源 IP 下的所有频道明细。page 为 None 时返回全部结果。"""
    conn = _get_conn()

    if page is not None:
        total = conn.execute(
            "SELECT COUNT(*) AS cnt FROM persistent_scan_results WHERE source_ip = ?",
            (source_ip,)
        ).fetchone()['cnt']
        offset = (page - 1) * size
        rows = conn.execute(
            """SELECT id, url, name, category, province, city, source_ip, platform,
                      resolution, codec, delay, bandwidth, stability,
                      quality_status, consecutive_failures,
                      last_checked_at, first_seen_at, last_updated_at, validated
               FROM persistent_scan_results
               WHERE source_ip = ?
               ORDER BY stability DESC, bandwidth DESC
               LIMIT ? OFFSET ?""",
            (source_ip, size, offset)
        ).fetchall()
        return {'total': total, 'items': [dict(r) for r in rows], 'page': page, 'page_size': size}
    else:
        rows = conn.execute(
            """SELECT id, url, name, category, province, city, source_ip, platform,
                      resolution, codec, delay, bandwidth, stability,
                      quality_status, consecutive_failures,
                      last_checked_at, first_seen_at, last_updated_at, validated
               FROM persistent_scan_results
               WHERE source_ip = ?
               ORDER BY stability DESC, bandwidth DESC""",
            (source_ip,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_persistent_for_detection_table():
    """获取所有持久化结果用于检测概览表格。"""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT id, name, source_ip, platform, quality_status,
                  consecutive_failures, last_checked_at,
                  stability, delay, bandwidth
           FROM persistent_scan_results
           ORDER BY
             CASE WHEN last_checked_at IS NULL THEN 1 ELSE 0 END,
             last_checked_at DESC"""
    ).fetchall()
    return [dict(r) for r in rows]


def get_persistent_stats():
    """按 quality_status 统计持久化结果数量。"""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT quality_status, COUNT(*) as cnt
           FROM persistent_scan_results
           GROUP BY quality_status"""
    ).fetchall()
    result = {r['quality_status']: r['cnt'] for r in rows}
    total = sum(result.values())
    result['total'] = total
    return result


def get_persistent_grouped():
    """两级分组：platform → source_ip，返回完整分组结构。"""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT platform, source_ip,
                  COUNT(*) as channel_count,
                  ROUND(AVG(stability), 1) as avg_stability,
                  ROUND(AVG(delay), 1) as avg_delay,
                  ROUND(AVG(bandwidth), 1) as avg_bandwidth,
                  SUM(CASE WHEN quality_status='good' THEN 1 ELSE 0 END) as good_count,
                  SUM(CASE WHEN quality_status='poor' THEN 1 ELSE 0 END) as poor_count,
                  SUM(CASE WHEN quality_status='unreachable' THEN 1 ELSE 0 END) as unreachable_count,
                  SUM(CASE WHEN quality_status='pending' THEN 1 ELSE 0 END) as pending_count,
                  MIN(first_seen_at) as first_seen,
                  MAX(COALESCE(last_checked_at, last_updated_at)) as last_updated
           FROM persistent_scan_results
           GROUP BY platform, source_ip
           ORDER BY platform, channel_count DESC"""
    ).fetchall()

    platforms = {}
    for r in rows:
        plat = r['platform'] or '未知'
        if plat not in platforms:
            platforms[plat] = {
                'platform': plat,
                'source_count': 0,
                'channel_count': 0,
                'total_stability': 0,
                'sources': [],
            }
        p = platforms[plat]
        p['source_count'] += 1
        p['channel_count'] += r['channel_count']
        p['total_stability'] += r['avg_stability'] * r['channel_count']
        p['sources'].append({
            'source_ip': r['source_ip'],
            'channel_count': r['channel_count'],
            'avg_stability': r['avg_stability'],
            'avg_delay': r['avg_delay'],
            'avg_bandwidth': r['avg_bandwidth'],
            'good_count': r['good_count'],
            'poor_count': r['poor_count'],
            'unreachable_count': r['unreachable_count'],
            'pending_count': r['pending_count'],
            'first_seen': r['first_seen'],
            'last_updated': r['last_updated'],
        })

    result = []
    for plat, data in platforms.items():
        avg_stab = round(data['total_stability'] / data['channel_count'], 1) if data['channel_count'] else 0
        result.append({
            'platform': plat,
            'source_count': data['source_count'],
            'channel_count': data['channel_count'],
            'avg_stability': avg_stab,
            'sources': data['sources'],
        })
    result.sort(key=lambda x: x['channel_count'], reverse=True)
    return result


def get_persistent_by_url(url):
    """按 URL 查询单条持久化结果。"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT consecutive_failures, quality_status FROM persistent_scan_results WHERE url = ?",
        (url,)
    ).fetchone()
    return dict(row) if row else None


def update_persistent_check(url, ok, stability=None, delay=None,
                            bandwidth=None, resolution=None, codec=None):
    """更新单条持久化结果的检测状态。"""
    conn = _get_conn()
    now = now_str()
    if ok:
        # 连接成功：重置失败计数，根据指标更新质量状态
        # 若未传入指标（如检测轮次），使用数据库中已有的值
        if stability is None:
            row = conn.execute(
                "SELECT stability, delay, bandwidth FROM persistent_scan_results WHERE url=?",
                (url,)
            ).fetchone()
            if row:
                stability = row['stability']
                if delay is None:
                    delay = row['delay']
                if bandwidth is None:
                    bandwidth = row['bandwidth']
        quality = _evaluate_quality(stability, delay, bandwidth)
        conn.execute(
            """UPDATE persistent_scan_results
               SET consecutive_failures=0, last_checked_at=?,
                   quality_status=?, validated=1,
                   stability=COALESCE(?, stability),
                   delay=COALESCE(?, delay),
                   bandwidth=COALESCE(?, bandwidth),
                   resolution=COALESCE(?, resolution),
                   codec=COALESCE(?, codec)
               WHERE url=?""",
            (now, quality, stability, delay, bandwidth, resolution, codec, url)
        )
    else:
        # 连接失败：失败计数 +1
        conn.execute(
            """UPDATE persistent_scan_results
               SET consecutive_failures=consecutive_failures+1,
                   last_checked_at=?, quality_status='unreachable'
               WHERE url=?""",
            (now, url)
        )
    conn.commit()


def _evaluate_quality(stability, delay, bandwidth):
    """根据检测指标判定质量等级。"""
    if stability is None:
        return 'unreachable'
    # 确保数值类型（数据库可能存储为字符串）
    try:
        stability = float(stability) if stability else 0
    except (TypeError, ValueError):
        return 'unreachable'
    try:
        delay = float(delay) if delay not in (None, '') else None
    except (TypeError, ValueError):
        delay = None
    try:
        bandwidth = float(bandwidth) if bandwidth not in (None, '') else None
    except (TypeError, ValueError):
        bandwidth = None
    if stability >= 60 and (delay is None or delay < 2000) and (bandwidth is None or bandwidth >= 300):
        return 'good'
    if stability >= 30:
        return 'poor'
    return 'unreachable'


def delete_persistent_by_threshold(threshold):
    """删除连续失败次数达到阈值的持久化结果。返回删除数量。"""
    conn = _get_conn()
    cursor = conn.execute(
        "DELETE FROM persistent_scan_results WHERE consecutive_failures >= ?",
        (threshold,)
    )
    conn.commit()
    return cursor.rowcount


def delete_persistent_by_id(row_id):
    """删除单条持久化结果。"""
    conn = _get_conn()
    conn.execute("DELETE FROM persistent_scan_results WHERE id = ?", (row_id,))
    conn.commit()


def get_persistent_for_test():
    """获取已验证且质量好的持久化结果，用于融合测速。
    返回 [(channel_info_dict, url)] 格式，与 test_engine 的 test_list 兼容。"""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT name, url FROM persistent_scan_results
           WHERE validated = 1 AND quality_status = 'good'
           ORDER BY stability DESC, bandwidth DESC"""
    ).fetchall()
    return [({'name': r['name']}, r['url']) for r in rows]


def get_all_persistent_for_check():
    """获取所有持久化结果用于检测循环。"""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT id, url, name, stability, delay, bandwidth
           FROM persistent_scan_results
           ORDER BY id"""
    ).fetchall()
    return [dict(r) for r in rows]


def get_pending_persistent():
    """获取所有待验证的持久化结果。"""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT id, url, name, stability, delay, bandwidth, resolution, codec
           FROM persistent_scan_results
           WHERE validated = 0
           ORDER BY id"""
    ).fetchall()
    return [dict(r) for r in rows]

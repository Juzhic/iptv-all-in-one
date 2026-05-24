"""IPTV 测速结果 SQLite 数据库模块。"""
import json
import os
import sqlite3
import threading
from datetime import datetime

DB_PATH = 'iptv.db'
MAX_RUNS = 50

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
    """)
    conn.commit()


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
                codec, is_h265, sample_seconds, passed, reason, cost_seconds)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    run_data['run_id'],
                    r.get('channel', ''),
                    r.get('url', ''),
                    r.get('resolution', ''),
                    r.get('bandwidth_MBps', 0),
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
        "SELECT channel, url FROM run_results WHERE run_id = ? AND passed = 1 ORDER BY id",
        (run['run_id'],)
    ).fetchall()
    return [dict(r) for r in results]


def get_run_history(limit=50):
    """获取历史轮次列表（不含详细结果）。"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
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
        "SELECT * FROM run_results WHERE run_id = ? ORDER BY id",
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
        "SELECT * FROM run_results WHERE run_id = ? ORDER BY channel, id",
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

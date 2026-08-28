# -*- coding: utf-8 -*-
"""SQL-aggregated data for the operations dashboard and source table."""

from __future__ import annotations

from urllib.parse import urlsplit

import database as db


SOURCE_SORT_COLUMNS = {
    'source_url': 'source_url',
    'channels_total': 'channels_total',
    'channels_passed': 'channels_passed',
    'pass_rate': 'pass_rate',
    'avg_bandwidth': 'avg_bandwidth',
    'avg_quality': 'avg_quality',
    'h265_ratio': 'h265_ratio',
    'score': 'score',
}

UNKNOWN_SOURCE_LABEL = '(未知来源)'
SCAN_SOURCE_LABEL_PREFIX = db.SCAN_SOURCE_LABEL_PREFIX
SCAN_SOURCE_PLATFORM_FALLBACK = db.SCAN_SOURCE_PLATFORM_FALLBACK


def _number(value, default=0.0):
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _integer(value, default=0):
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _scan_source_label_sql(platform_column):
    """Build the SQL display label for a stream found in the scan pool."""
    return f"""(
        '{SCAN_SOURCE_LABEL_PREFIX}' ||
        CASE
          WHEN NULLIF(TRIM({platform_column}), '') IS NULL
               OR LOWER(TRIM({platform_column})) IN ('unknown', 'n/a', 'na')
               OR TRIM({platform_column}) = '未知'
          THEN '{SCAN_SOURCE_PLATFORM_FALLBACK}'
          ELSE TRIM({platform_column})
        END
    )"""


def _source_display_sql():
    """Resolve a stored subscription URL or the scan-pool provenance label."""
    return f"""COALESCE(
        NULLIF(TRIM(rr.source_url), ''),
        CASE WHEN psr.url IS NOT NULL THEN {_scan_source_label_sql('psr.platform')}
             ELSE '{UNKNOWN_SOURCE_LABEL}' END
    )"""


def calculate_source_score(
    channels_passed,
    channels_total,
    template_total,
    avg_bandwidth,
    avg_quality,
):
    """Calculate the existing weighted 0–100 subscription source score."""
    passed = max(0, _integer(channels_passed))
    total = max(0, _integer(channels_total))
    template = max(0, _integer(template_total))
    coverage = min(passed / template, 1) if template else 0
    pass_rate = min(passed / total, 1) if total else 0
    bandwidth = min(max(_number(avg_bandwidth), 0) / 10, 1)
    quality = min(max(_number(avg_quality), 0) / 5, 1)
    return round(coverage * 30 + pass_rate * 30 + bandwidth * 20 + quality * 20, 1)


def mask_source_url(value):
    """Mask credentials, path and query while retaining a useful source host."""
    raw = db.normalize_scan_source_label((value or '').strip())
    if raw.startswith(SCAN_SOURCE_LABEL_PREFIX):
        return raw
    if not raw or raw == UNKNOWN_SOURCE_LABEL:
        return UNKNOWN_SOURCE_LABEL
    try:
        parsed = urlsplit(raw)
        if not parsed.scheme or not parsed.hostname:
            return '••••••'
        host = parsed.hostname
        if ':' in host and not host.startswith('['):
            host = f'[{host}]'
        port = f':{parsed.port}' if parsed.port else ''
        return f'{parsed.scheme}://{host}{port}/•••'
    except (TypeError, ValueError):
        return '••••••'


def _template_channel_count():
    raw = db.get_config_data('demo') or ''
    channels = set()
    for line in raw.splitlines()[:50_000]:
        line = line.strip()
        if not line or line.startswith('#') or line.endswith(',#genre#'):
            continue
        channels.add(line.split(',', 1)[0].strip())
    return len(channels)


def _source_aggregate_rows(conn, run_id):
    source_sql = _source_display_sql()
    rows = conn.execute(
        f"""SELECT {source_sql} AS source_url,
                  COUNT(DISTINCT channel) AS channels_total,
                  COUNT(DISTINCT CASE WHEN passed=1 THEN channel END) AS channels_passed,
                  AVG(CASE WHEN passed=1 AND "bandwidth_MBps" > 0 THEN "bandwidth_MBps" END) AS avg_bandwidth,
                  AVG(CASE WHEN passed=1 AND quality_score > 0 THEN quality_score END) AS avg_quality,
                  AVG(CASE WHEN is_h265=1 THEN 1 ELSE 0 END) AS h265_ratio
           FROM run_results rr
           LEFT JOIN persistent_scan_results psr
             ON digest(psr.url, 'sha256') = digest(rr.url, 'sha256')
            AND psr.url = rr.url
           WHERE rr.run_id=%s
           GROUP BY {source_sql}""",
        (run_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _decorate_source(row, template_total, reveal_url=False):
    total = _integer(row.get('channels_total'))
    passed = _integer(row.get('channels_passed'))
    avg_bandwidth = round(_number(row.get('avg_bandwidth')), 2)
    avg_quality = round(_number(row.get('avg_quality')), 2)
    source_url = row.get('source_url') or UNKNOWN_SOURCE_LABEL
    return {
        'source_url': source_url if reveal_url else mask_source_url(source_url),
        'channels_total': total,
        'channels_passed': passed,
        'pass_rate': round(passed / total, 4) if total else 0,
        'avg_bandwidth': avg_bandwidth,
        'avg_quality': avg_quality,
        'h265_ratio': round(_number(row.get('h265_ratio')), 4),
        'score': calculate_source_score(
            passed, total, template_total, avg_bandwidth, avg_quality,
        ),
    }


def get_sources_page(
    *,
    page=1,
    size=20,
    search='',
    sort_by='score',
    sort_order='desc',
    reveal_url=False,
):
    """Return one SQL-paginated, searched and sorted latest source page."""
    page = max(1, _integer(page, 1))
    size = max(1, min(200, _integer(size, 20)))
    sort_column = SOURCE_SORT_COLUMNS.get(sort_by, 'score')
    order = 'ASC' if str(sort_order).lower() == 'asc' else 'DESC'
    conn = db._get_conn()
    latest = conn.execute(
        "SELECT run_id, finished_at FROM runs "
        "ORDER BY finished_at DESC NULLS LAST, id DESC LIMIT 1"
    ).fetchone()
    if not latest:
        return {'items': [], 'total': 0, 'page': page, 'page_size': size, 'last_updated': None}

    template_total = _template_channel_count()
    search = (search or '').strip()[:256]
    search_where = ""
    search_params = []
    if search:
        search_where = "WHERE source_url ILIKE %s"
        search_params.append(f'%{search}%')

    source_sql = _source_display_sql()
    aggregate_sql = f"""SELECT
            {source_sql} AS source_url,
            COUNT(DISTINCT channel) AS channels_total,
            COUNT(DISTINCT CASE WHEN passed=1 THEN channel END) AS channels_passed,
            CASE WHEN COUNT(DISTINCT channel) > 0
                 THEN COUNT(DISTINCT CASE WHEN passed=1 THEN channel END)::DOUBLE PRECISION
                      / NULLIF(COUNT(DISTINCT channel), 0)
                 ELSE 0.0 END AS pass_rate,
            COALESCE(AVG(CASE WHEN passed=1 AND "bandwidth_MBps" > 0 THEN "bandwidth_MBps" END), 0) AS avg_bandwidth,
            COALESCE(AVG(CASE WHEN passed=1 AND quality_score > 0 THEN quality_score END), 0) AS avg_quality
            ,COALESCE(AVG(CASE WHEN is_h265=1 THEN 1 ELSE 0 END), 0) AS h265_ratio
        FROM run_results rr
        LEFT JOIN persistent_scan_results psr
          ON digest(psr.url, 'sha256') = digest(rr.url, 'sha256')
         AND psr.url = rr.url
        WHERE rr.run_id=%s
        GROUP BY {source_sql}"""
    # Score is calculated in SQL so LIMIT/OFFSET apply after score sorting.
    template_denominator = max(template_total, 1)
    score_sql = """(
        CASE WHEN %s > 0 THEN LEAST(agg.channels_passed::DOUBLE PRECISION / %s, 1.0) * 30 ELSE 0.0 END +
        LEAST(agg.pass_rate, 1.0) * 30 +
        LEAST(agg.avg_bandwidth / 10.0, 1.0) * 20 +
        LEAST(agg.avg_quality / 5.0, 1.0) * 20
    )"""
    total_row = conn.execute(
        f"SELECT COUNT(*) AS cnt FROM ({aggregate_sql}) agg {search_where}",
        [latest['run_id'], *search_params],
    ).fetchone()
    offset = (page - 1) * size
    order_expression = score_sql if sort_column == 'score' else f'agg.{sort_column}'
    nulls_order = 'NULLS FIRST' if order == 'ASC' else 'NULLS LAST'
    rows = conn.execute(
        f"""SELECT agg.*, {score_sql} AS score
            FROM ({aggregate_sql}) agg
            {search_where}
            ORDER BY {order_expression} {order} {nulls_order}, agg.source_url ASC NULLS FIRST
            LIMIT %s OFFSET %s""",
        # SELECT score always needs one denominator; score ORDER needs another.
        [template_total, template_denominator, latest['run_id'], *search_params]
        + ([template_total, template_denominator] if sort_column == 'score' else [])
        + [size, offset],
    ).fetchall()

    items = []
    for raw_row in rows:
        row = dict(raw_row)
        item = _decorate_source(row, template_total, reveal_url=reveal_url)
        # Keep the SQL value so server-side order and displayed value agree.
        item['score'] = round(_number(row.get('score')), 1)
        items.append(item)
    return {
        'items': items,
        'total': _integer(total_row['cnt'] if total_row else 0),
        'page': page,
        'page_size': size,
        'last_updated': latest['finished_at'],
    }


def _scan_dashboard(conn, trend_limit):
    recent = conn.execute(
        """SELECT scan_id, started_at, finished_at, total_raw, total_deduped,
                  total_fast_pass, total_deep_pass
           FROM scan_runs WHERE status='completed'
           ORDER BY id DESC LIMIT %s""",
        (max(2, trend_limit),),
    ).fetchall()
    rows = [dict(row) for row in recent]
    latest = dict(rows[0]) if rows else None
    previous = rows[1] if len(rows) > 1 else None
    if latest:
        latest['deltas'] = {
            key: _integer(latest.get(key)) - _integer((previous or {}).get(key))
            for key in ('total_raw', 'total_deduped', 'total_fast_pass', 'total_deep_pass')
        }

    pool_row = conn.execute(
        """SELECT
              SUM(CASE WHEN quality_status='good' THEN 1 ELSE 0 END) AS good,
              SUM(CASE WHEN quality_status='poor' THEN 1 ELSE 0 END) AS poor,
              SUM(CASE WHEN quality_status='unreachable' THEN 1 ELSE 0 END) AS unreachable,
              SUM(CASE WHEN quality_status='pending' THEN 1 ELSE 0 END) AS pending,
              AVG(stability) AS avg_stability,
              AVG(delay) AS avg_delay_ms,
              AVG(bandwidth) AS "avg_bandwidth_MBps"
           FROM persistent_scan_results WHERE deleted_at IS NULL"""
    ).fetchone() or {}
    pool = {key: _integer(pool_row.get(key)) for key in ('good', 'poor', 'unreachable', 'pending')}
    denominator = pool['good'] + pool['poor'] + pool['unreachable']
    pool.update({
        'good_rate': round(pool['good'] / denominator, 4) if denominator else 0,
        'good_rate_percent': round(pool['good'] / denominator * 100, 2) if denominator else 0,
        'avg_stability': round(_number(pool_row.get('avg_stability')), 1),
        'avg_delay_ms': round(_number(pool_row.get('avg_delay_ms')), 1),
        'avg_bandwidth_MBps': round(_number(pool_row.get('avg_bandwidth_MBps')), 2),
    })
    return {'latest': latest, 'pool': pool, 'trend': list(reversed(rows[:trend_limit]))}


def _subscription_trend(conn, trend_limit):
    source_sql = _source_display_sql()
    rows = conn.execute(
        f"""SELECT recent.run_id, recent.finished_at,
                  COUNT(DISTINCT CASE WHEN rr.id IS NOT NULL
                        THEN {source_sql} END) AS source_count,
                  COUNT(DISTINCT rr.channel) AS channels_total,
                  COUNT(DISTINCT CASE WHEN rr.passed=1 THEN rr.channel END) AS channels_passed,
                  AVG(CASE WHEN rr.passed=1 AND rr."bandwidth_MBps">0 THEN rr."bandwidth_MBps" END) AS "avg_bandwidth_MBps",
                  AVG(CASE WHEN rr.passed=1 AND rr.quality_score>0 THEN rr.quality_score END) AS avg_quality
           FROM (SELECT id, run_id, finished_at FROM runs ORDER BY id DESC LIMIT %s) recent
           LEFT JOIN run_results rr ON rr.run_id=recent.run_id
           LEFT JOIN persistent_scan_results psr
             ON digest(psr.url, 'sha256') = digest(rr.url, 'sha256')
            AND psr.url=rr.url
           GROUP BY recent.id, recent.run_id, recent.finished_at
           ORDER BY recent.id ASC""",
        (trend_limit,),
    ).fetchall()
    trend = []
    for raw in rows:
        row = dict(raw)
        total = _integer(row.get('channels_total'))
        passed = _integer(row.get('channels_passed'))
        trend.append({
            'run_id': row.get('run_id'),
            'finished_at': row.get('finished_at'),
            'source_count': _integer(row.get('source_count')),
            'channels_total': total,
            'channels_passed': passed,
            'pass_rate': round(passed / total, 4) if total else 0,
            'avg_bandwidth_MBps': round(_number(row.get('avg_bandwidth_MBps')), 2),
            'avg_quality': round(_number(row.get('avg_quality')), 2),
        })
    return trend


def _subscription_dashboard(conn, trend_limit):
    trend = _subscription_trend(conn, trend_limit)
    latest = dict(trend[-1]) if trend else None
    best_source = None
    degraded_source = None
    if latest:
        template_total = _template_channel_count()
        latest_rows = _source_aggregate_rows(conn, latest['run_id'])
        decorated = [_decorate_source(row, template_total) for row in latest_rows]
        if decorated:
            best_source = max(decorated, key=lambda item: item['score'])

        if len(trend) > 1:
            previous_rows = _source_aggregate_rows(conn, trend[-2]['run_id'])
            previous_scores = {
                row.get('source_url'): _decorate_source(row, template_total)['score']
                for row in previous_rows
            }
            regressions = []
            for raw, item in zip(latest_rows, decorated):
                source_url = raw.get('source_url')
                if source_url in previous_scores:
                    delta = round(item['score'] - previous_scores[source_url], 1)
                    regressions.append({**item, 'score_delta': delta})
            negative = [item for item in regressions if item['score_delta'] < 0]
            if negative:
                degraded_source = min(negative, key=lambda item: item['score_delta'])
    return {
        'latest': latest,
        'trend': trend,
        'best_source': best_source,
        'degraded_source': degraded_source,
    }


def _task_dashboard():
    empty = {
        name: {'task_id': None, 'state': 'idle', 'progress': 0, 'started_at': None, 'error': ''}
        for name in ('test', 'scan', 'ip_scan', 'detection')
    }
    try:
        snapshot = getattr(__import__('scanner_integration'), 'get_tasks_snapshot', None)
        if snapshot:
            data = snapshot()
            if isinstance(data, dict):
                empty.update(data)
                return empty
    except Exception:
        pass
    try:
        aliases = {'system_test': 'test', 'test': 'test', 'scan': 'scan', 'ip_scan': 'ip_scan', 'detection': 'detection'}
        for lease in db.list_task_leases():
            key = aliases.get(lease.get('task_type'))
            if not key:
                continue
            empty[key] = {
                'task_id': lease.get('task_id'),
                'state': lease.get('state') or 'idle',
                'progress': lease.get('progress') or 0,
                'started_at': lease.get('started_at'),
                'error': lease.get('error') or '',
            }
    except Exception:
        pass
    return empty


def get_dashboard(trend_limit=10):
    trend_limit = max(1, min(30, _integer(trend_limit, 10)))
    conn = db._get_conn()
    return {
        'scan': _scan_dashboard(conn, trend_limit),
        'subscriptions': _subscription_dashboard(conn, trend_limit),
        'tasks': _task_dashboard(),
    }

"""Real PostgreSQL 18 integration coverage for the database layer.

The module is intentionally safe for developer machines: a missing database is
skipped locally, while CI (or ``IPTV_REQUIRE_DATABASE=1``) treats it as a hard
failure.  Tests only create rows carrying a random prefix and never drop or
truncate application objects.
"""

from __future__ import annotations

import multiprocessing
import os
import queue
import uuid
from contextlib import ExitStack
from unittest.mock import patch

import psycopg
import pytest
from psycopg.rows import dict_row

import database.db as db


_PREFIX = f"itpg{uuid.uuid4().hex}"
_URL_BASE = f"https://integration.invalid/{_PREFIX}/"
_DB_CONFIG = {
    'host': os.environ.get('DB_HOST', 'postgres'),
    'port': int(os.environ.get('DB_PORT', '5432')),
    'user': os.environ.get('DB_USER', 'iptv_app'),
    'password': os.environ.get('DB_PASSWORD', ''),
    'database': os.environ.get('DB_NAME', 'iptv_all_in_one'),
}


def _env_true(name: str) -> bool:
    return os.environ.get(name, '').strip().lower() in {'1', 'true', 'yes', 'on'}


def _database_is_required() -> bool:
    return _env_true('CI') or _env_true('IPTV_REQUIRE_DATABASE')


def _raw_connect(*, timeout: int = 3):
    return psycopg.connect(
        host=_DB_CONFIG['host'],
        port=_DB_CONFIG['port'],
        user=_DB_CONFIG['user'],
        password=_DB_CONFIG['password'],
        dbname=_DB_CONFIG['database'],
        connect_timeout=timeout,
        autocommit=True,
        row_factory=dict_row,
        application_name='iptv-test-integration',
    )


def _cleanup_prefixed_rows() -> None:
    """Delete only rows owned by this module, in foreign-key-safe order."""
    pattern = f'{_PREFIX}%'
    url_pattern = f'{_URL_BASE}%'
    with _raw_connect() as conn:
        with conn.transaction():
            conn.execute("DELETE FROM task_leases WHERE task_type LIKE %s", (pattern,))
            conn.execute("DELETE FROM run_logs WHERE run_id LIKE %s", (pattern,))
            conn.execute("DELETE FROM runs WHERE run_id LIKE %s", (pattern,))
            conn.execute("DELETE FROM scan_yield_stats WHERE scan_id LIKE %s", (pattern,))
            conn.execute("DELETE FROM scan_runs WHERE scan_id LIKE %s", (pattern,))
            conn.execute("DELETE FROM quality_history WHERE url LIKE %s", (url_pattern,))
            conn.execute("DELETE FROM persistent_scan_results WHERE url LIKE %s", (url_pattern,))
            conn.execute("DELETE FROM config_data WHERE \"key\" LIKE %s", (pattern,))


def _without_startup_retention():
    """Keep init idempotence tests from pruning unrelated retained data."""
    stack = ExitStack()
    stack.enter_context(patch.object(db, 'cleanup_old_run_logs', return_value=0))
    stack.enter_context(patch.object(db, 'cleanup_old_scan_logs', return_value=0))
    stack.enter_context(patch.object(db, 'cleanup_stale_persistent', return_value=0))
    stack.enter_context(patch.object(db, 'cleanup_old_ip_scan_logs', return_value=0))
    return stack


@pytest.fixture(scope='module', autouse=True)
def _postgres_database():
    # Refuse to point mutation tests at a plausibly production database unless
    # the operator explicitly opted in. CI always uses the dedicated iptv_test.
    explicit_local_opt_in = _env_true('IPTV_RUN_POSTGRES_INTEGRATION')
    if (
        not _database_is_required()
        and 'test' not in _DB_CONFIG['database'].casefold()
        and not explicit_local_opt_in
    ):
        pytest.skip(
            'PostgreSQL integration tests require a test-named DB_NAME or '
            'IPTV_RUN_POSTGRES_INTEGRATION=1'
        )

    try:
        with _raw_connect() as probe:
            probe.execute('SELECT 1').fetchone()
    except psycopg.Error as exc:
        message = (
            'PostgreSQL integration database is unavailable at '
            f"{_DB_CONFIG['host']}:{_DB_CONFIG['port']}/{_DB_CONFIG['database']}: {exc}"
        )
        if _database_is_required():
            pytest.fail(message, pytrace=False)
        pytest.skip(message)

    previous_config = db._db_config
    db.close_thread_connection()
    db._db_config = dict(_DB_CONFIG)
    try:
        with _without_startup_retention():
            db.init_db()
        _cleanup_prefixed_rows()
        yield
    finally:
        db.close_thread_connection()
        try:
            _cleanup_prefixed_rows()
        finally:
            db._db_config = previous_config


def _run_payload(run_id: str, *, bandwidth: float, pass_rate: float):
    now = '2026-08-28 12:00:00'
    return {
        'run_id': run_id,
        'started_at': now,
        'finished_at': now,
        'duration_seconds': 1.25,
        'summary': {
            'total_tested': 1,
            'total_passed': 1,
            'total_failed': 0,
            'pass_rate': pass_rate,
            'unique_channels_passed': 1,
            'unique_channels_total': 1,
        },
        'results': [{
            'channel': f'{_PREFIX}-channel',
            'url': f'{_URL_BASE}{run_id}',
            'resolution': '1920x1080',
            'bandwidth_MBps': bandwidth,
            'connection_latency_ms': 12.5,
            'quality_score': 4.75,
            'output_updated_at': now,
            'codec': 'h264',
            'is_h265': False,
            'sample_seconds': 1.5,
            'passed': True,
            'reason': '',
            'cost_seconds': 1.25,
            'source_url': f'{_PREFIX}-source',
        }],
    }


def _insert_run_without_retention(payload) -> None:
    with patch.object(db, '_cleanup_old_runs', return_value=None):
        db.insert_run(payload)


def _insert_scan_run_without_retention(scan_id: str) -> None:
    with patch.object(db, '_cleanup_old_scan_runs', return_value=None):
        db.insert_scan_run({
            'scan_id': scan_id,
            'started_at': '2026-08-28 12:00:00',
            'finished_at': '2026-08-28 12:01:00',
            'status': 'completed',
            'trigger_source': 'integration',
            'platforms_used': 'integration',
            'duration_seconds': 60.25,
        })


def _acquire_lease_worker(config, task_type, task_id, owner, start_event, result_queue):
    """Spawn-safe worker: each process owns an independent application lock."""
    import database.db as worker_db

    worker_db.close_thread_connection()
    worker_db._db_config = dict(config)
    try:
        if not start_event.wait(15):
            raise TimeoutError('lease start barrier timed out')
        acquired, snapshot = worker_db.acquire_task_lease(
            task_type, task_id, owner, lease_seconds=60
        )
        result_queue.put(('ok', acquired, snapshot.get('task_id') if snapshot else None))
    except BaseException as exc:  # propagated to the parent as data
        result_queue.put(('error', type(exc).__name__, str(exc)))
    finally:
        worker_db.close_thread_connection()


def test_postgresql_18_and_init_db_are_idempotent():
    with _raw_connect() as conn:
        version = conn.info.server_version
    assert 180000 <= version < 190000

    with _without_startup_retention():
        db.init_db()
        db.init_db()

    conn = db._get_conn()
    migration = conn.execute(
        "SELECT description FROM schema_migrations WHERE version = %s",
        (db.SCHEMA_VERSION,),
    ).fetchone()
    extension = conn.execute(
        "SELECT extname FROM pg_extension WHERE extname = 'pgcrypto'"
    ).fetchone()
    assert migration['description'] == 'PostgreSQL 18 baseline schema'
    assert extension['extname'] == 'pgcrypto'


def test_crud_explicit_rollback_and_foreign_key_cascade():
    config_key = f'{_PREFIX}config'
    rollback_key = f'{_PREFIX}rollback'
    db.set_config_data(config_key, 'first')
    assert db.get_config_data(config_key) == 'first'
    db.set_config_data(config_key, 'second')
    assert db.get_config_data(config_key) == 'second'

    class ExpectedRollback(Exception):
        pass

    conn = db._get_conn()
    with pytest.raises(ExpectedRollback):
        with conn.transaction():
            conn.execute(
                'INSERT INTO config_data ("key", content, updated_at) VALUES (%s, %s, %s)',
                (rollback_key, 'must-roll-back', '2026-08-28 12:00:00'),
            )
            raise ExpectedRollback
    assert conn.execute(
        'SELECT 1 FROM config_data WHERE "key" = %s', (rollback_key,)
    ).fetchone() is None

    run_id = f'{_PREFIX}cascade'
    _insert_run_without_retention(_run_payload(run_id, bandwidth=1.5, pass_rate=100.0))
    assert conn.execute(
        'SELECT 1 FROM run_results WHERE run_id = %s', (run_id,)
    ).fetchone()
    conn.execute('DELETE FROM runs WHERE run_id = %s', (run_id,))
    assert conn.execute(
        'SELECT 1 FROM run_results WHERE run_id = %s', (run_id,)
    ).fetchone() is None


def test_on_conflict_identity_and_mixed_case_bandwidth_key():
    first_run = f'{_PREFIX}identity1'
    second_run = f'{_PREFIX}identity2'
    _insert_run_without_retention(
        _run_payload(first_run, bandwidth=1.2345, pass_rate=66.67)
    )
    conn = db._get_conn()
    original = conn.execute(
        'SELECT id, pass_rate FROM runs WHERE run_id = %s', (first_run,)
    ).fetchone()

    _insert_run_without_retention(
        _run_payload(first_run, bandwidth=2.75, pass_rate=50.5)
    )
    updated = conn.execute(
        'SELECT id, pass_rate FROM runs WHERE run_id = %s', (first_run,)
    ).fetchone()
    bandwidth = conn.execute(
        'SELECT "bandwidth_MBps" FROM run_results WHERE run_id = %s', (first_run,)
    ).fetchone()

    assert updated['id'] == original['id']
    assert updated['pass_rate'] == pytest.approx(50.5)
    assert set(bandwidth) == {'bandwidth_MBps'}
    assert bandwidth['bandwidth_MBps'] == pytest.approx(2.75)

    _insert_run_without_retention(
        _run_payload(second_run, bandwidth=3.5, pass_rate=100.0)
    )
    second_id = conn.execute(
        'SELECT id FROM runs WHERE run_id = %s', (second_run,)
    ).fetchone()['id']
    identity_sequence = conn.execute(
        "SELECT pg_get_serial_sequence('runs', 'id') AS sequence_name"
    ).fetchone()['sequence_name']
    assert identity_sequence
    assert second_id > original['id']


def test_digest_indexes_accept_4096_char_urls_and_scan_search_null_sorting():
    scan_id = f'{_PREFIX}scan'
    _insert_scan_run_without_retention(scan_id)
    long_url = _URL_BASE + ('x' * (4096 - len(_URL_BASE)))
    assert len(long_url) == 4096

    db.insert_scan_results(scan_id, [{
        'name': 'MiXeDCaseChannel',
        'url': long_url,
        'category': 'integration',
        'platform': _PREFIX,
        'bandwidth': 1.25,
        'stability': 80,
    }, {
        'name': 'HighestBandwidth',
        'url': f'{_URL_BASE}highest',
        'category': 'integration',
        'platform': _PREFIX,
        'bandwidth': 2.5,
        'stability': 90,
    }, {
        'name': 'NullBandwidth',
        'url': f'{_URL_BASE}null',
        'category': 'integration',
        'platform': _PREFIX,
        'bandwidth': None,
        'stability': 70,
    }])
    # Exercise the SHA-256 expression-index ON CONFLICT path on the 4096-char URL.
    db.insert_scan_results(scan_id, [{
        'name': 'MiXeDCaseChannelUpdated',
        'url': long_url,
        'category': 'integration',
        'platform': _PREFIX,
        'bandwidth': 1.5,
        'stability': 85,
    }])

    conn = db._get_conn()
    stored = conn.execute(
        """SELECT name, length(url) AS url_length,
                  octet_length(digest(url, 'sha256')) AS digest_length
           FROM scan_results WHERE scan_id = %s AND url = %s""",
        (scan_id, long_url),
    ).fetchone()
    assert stored == {
        'name': 'MiXeDCaseChannelUpdated',
        'url_length': 4096,
        'digest_length': 32,
    }

    total, searched = db.get_scan_results(
        scan_id=scan_id, search='mixedcasechannelupdated', page=1, size=10
    )
    assert total == 1
    assert searched[0]['url'] == long_url

    total, sorted_rows = db.get_scan_results(
        scan_id=scan_id, sort_by='bandwidth', sort_order='desc', page=1, size=10
    )
    assert total == 3
    assert [row['bandwidth'] for row in sorted_rows] == [2.5, 1.5, None]


def test_persistent_digest_upsert_and_decimal_grouped_statistics():
    platform = f'{_PREFIX}platform'
    source_ip = f'{_PREFIX}.source'
    long_url = _URL_BASE + ('p' * (4096 - len(_URL_BASE)))
    rows = [{
        'url': f'{_URL_BASE}decimal1',
        'name': 'Decimal One',
        'platform': platform,
        'source_ip': source_ip,
        'stability': 70,
        'delay': 10.1,
        'bandwidth': 1.2,
    }, {
        'url': f'{_URL_BASE}decimal2',
        'name': 'Decimal Two',
        'platform': platform,
        'source_ip': source_ip,
        'stability': 80,
        'delay': 10.3,
        'bandwidth': 1.4,
    }]
    db.upsert_persistent_results(rows)
    db.upsert_persistent_results([{
        'url': long_url,
        'name': 'Long URL Before',
        'platform': f'{_PREFIX}long',
        'source_ip': source_ip,
        'stability': 50,
        'delay': 20.25,
        'bandwidth': 0.75,
    }])
    db.upsert_persistent_results([{
        'url': long_url,
        'name': 'Long URL After',
        'platform': f'{_PREFIX}long',
        'source_ip': source_ip,
        'stability': 60,
        'delay': 19.75,
        'bandwidth': 0.8,
    }])

    conn = db._get_conn()
    long_row = conn.execute(
        'SELECT name, length(url) AS url_length FROM persistent_scan_results WHERE url = %s',
        (long_url,),
    ).fetchone()
    assert long_row == {'name': 'Long URL After', 'url_length': 4096}

    groups = db.get_persistent_grouped()
    group = next(item for item in groups if item['platform'] == platform)
    source = next(item for item in group['sources'] if item['source_ip'] == source_ip)
    assert group['channel_count'] == 2
    assert group['avg_stability'] == pytest.approx(75.0)
    assert source['avg_stability'] == pytest.approx(75.0)
    assert source['avg_delay'] == pytest.approx(10.2)
    assert source['avg_bandwidth'] == pytest.approx(1.3)

    first_url = rows[0]['url']
    second_url = rows[1]['url']
    db.batch_update_persistent_checks([{
        'url': first_url,
        'name': 'Decimal One',
        'ok': True,
        'stability': 90,
        'delay': 9.9,
        'bandwidth': 1.5,
    }, {
        'url': second_url,
        'name': 'Decimal Two',
        'ok': False,
    }])
    failures = db.get_consecutive_failures_batch([first_url, second_url])
    assert failures == {first_url: 0, second_url: 1}
    first_updated = conn.execute(
        """SELECT validated, quality_status
           FROM persistent_scan_results WHERE url = %s""",
        (first_url,),
    ).fetchone()
    assert first_updated['validated'] == 1
    assert first_updated['quality_status'] in {'good', 'poor', 'unreachable'}


def test_concurrent_task_lease_has_exactly_one_winner():
    task_type = f'{_PREFIX}lease'
    context = multiprocessing.get_context('spawn')
    start_event = context.Event()
    result_queue = context.Queue()
    workers = [
        context.Process(
            target=_acquire_lease_worker,
            args=(
                _DB_CONFIG,
                task_type,
                f'{_PREFIX}task{index}',
                f'{_PREFIX}owner{index}',
                start_event,
                result_queue,
            ),
        )
        for index in range(4)
    ]
    for worker in workers:
        worker.start()
    start_event.set()

    results = []
    try:
        for _ in workers:
            results.append(result_queue.get(timeout=30))
    except queue.Empty:
        pytest.fail('timed out waiting for concurrent lease workers')
    finally:
        for worker in workers:
            worker.join(timeout=15)
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=5)

    errors = [result for result in results if result[0] == 'error']
    assert not errors
    assert sum(1 for result in results if result[1] is True) == 1
    snapshots = {result[2] for result in results}
    assert len(snapshots) == 1
    assert db.get_task_lease(task_type)['active'] is True


def test_closed_psycopg_connection_is_reconnected_for_next_statement():
    conn = db._get_conn()
    before_pid = conn.execute('SELECT pg_backend_pid() AS pid').fetchone()['pid']
    conn.commit()
    closed_raw_connection = conn._conn
    closed_raw_connection.close()

    after_pid = conn.execute('SELECT pg_backend_pid() AS pid').fetchone()['pid']
    assert conn._conn is not closed_raw_connection
    assert conn._conn.closed is False
    assert isinstance(after_pid, int)
    assert after_pid != before_pid

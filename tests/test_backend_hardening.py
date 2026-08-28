import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import database.db as db


class _Result:
    def __init__(self, row=None, rows=None):
        self._row = row
        self._rows = rows or []

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class BackendHardeningTests(unittest.TestCase):
    def test_channel_source_lookup_uses_digest_index_and_original_url_check(self):
        class Connection:
            def __init__(self):
                self.calls = []

            def execute(self, query, args=None):
                self.calls.append((query, args))
                if 'GROUP BY channel ORDER BY channel' in query:
                    return _Result(rows=[{'channel': 'CCTV-1', 'total': 1, 'passed': 1}])
                if 'SELECT * FROM run_results' in query:
                    return _Result(rows=[{
                        'id': 1,
                        'channel': 'CCTV-1',
                        'url': 'https://example.test/live',
                        'passed': 1,
                    }])
                if 'WITH requested(url)' in query:
                    return _Result(rows=[{
                        'url': 'https://example.test/live',
                        'platform': 'Quake 360',
                    }])
                raise AssertionError(query)

        connection = Connection()
        with patch.object(db, '_get_conn', return_value=connection):
            summary = db.get_channel_summary_with_source('run-1')

        self.assertEqual('Quake 360', summary['channels']['CCTV-1']['urls'][0]['platform'])
        query, args = next(
            (query, args) for query, args in connection.calls
            if 'WITH requested(url)' in query
        )
        self.assertIn('unnest(%s::TEXT[])', query)
        self.assertIn("digest(stored.url, 'sha256')", query)
        self.assertIn('stored.url = requested.url', query)
        self.assertEqual((['https://example.test/live'],), args)

    def test_closed_connection_reconnects_before_statement_execution(self):
        class Cursor:
            def __init__(self):
                self.calls = 0

            def execute(self, query, args=None):
                self.calls += 1
                return self

            def close(self):
                pass

        class RawConnection:
            def __init__(self, *, closed):
                self.closed = closed
                self.cursor_instance = Cursor()

            def cursor(self):
                return self.cursor_instance

            def close(self):
                self.closed = True

        old = RawConnection(closed=True)
        fresh = RawConnection(closed=False)
        connection = object.__new__(db.PostgreSQLConnection)
        connection._config = {}
        connection._conn = old
        connection._cursor = None
        connection._in_transaction = False

        with patch.object(connection, '_create_conn', return_value=fresh):
            connection.execute('SELECT 1')

        self.assertIs(connection._conn, fresh)
        self.assertEqual(fresh.cursor_instance.calls, 1)

    def test_in_flight_connection_failure_is_not_transparently_replayed(self):
        class Cursor:
            def __init__(self, raw):
                self.raw = raw
                self.calls = 0

            def execute(self, query, args=None):
                self.calls += 1
                self.raw.closed = True
                raise db.psycopg.errors.ConnectionFailure('connection lost')

            def close(self):
                pass

        class RawConnection:
            closed = False

            def __init__(self):
                self.close_calls = 0
                self.cursor_instance = Cursor(self)

            def cursor(self):
                return self.cursor_instance

            def close(self):
                self.close_calls += 1
                self.closed = True

        raw = RawConnection()
        connection = object.__new__(db.PostgreSQLConnection)
        connection._config = {}
        connection._conn = raw
        connection._cursor = None
        connection._in_transaction = False

        with patch.object(connection, '_create_conn') as create:
            with self.assertRaises(db.psycopg.OperationalError):
                connection.execute('INSERT INTO config_data VALUES (...)')

        create.assert_not_called()
        self.assertEqual(raw.cursor_instance.calls, 1)
        self.assertEqual(raw.close_calls, 1)

    def test_log_batcher_restores_failed_postgresql_batch_without_relocking(self):
        class Connection:
            @contextmanager
            def transaction(self):
                yield self

            def executemany(self, query, rows):
                raise RuntimeError('database disconnected')

        row = ('run-1', '2026-08-28 12:00:00', 'INFO', 'message')
        batcher = db.LogBatcher(max_size=1)
        with patch.object(db, '_get_conn', return_value=Connection()):
            with self.assertRaisesRegex(RuntimeError, 'database disconnected'):
                batcher.add('run_logs', row)

        self.assertEqual(list(batcher._buffer), [('run_logs', row)])

    def test_init_db_fails_closed_on_schema_error(self):
        class Connection:
            def execute(self, query, args=None):
                if 'information_schema.tables' in query:
                    return _Result(None)
                raise RuntimeError('ddl failed')

        with patch.object(db, '_get_conn', return_value=Connection()):
            with self.assertRaisesRegex(RuntimeError, 'ddl failed'):
                db.init_db()

    def test_schema_migration_does_not_swallow_column_failure(self):
        with patch.object(
            db, '_ensure_table_columns', side_effect=RuntimeError('alter failed')
        ):
            with self.assertRaisesRegex(RuntimeError, 'alter failed'):
                db._ensure_schema_migrations(object())

    def test_postgresql_schema_metadata_accepts_uppercase_dict_cursor_keys(self):
        rows = [
            {
                'TABLE_NAME': 'scan_runs',
                'DATA_TYPE': 'character varying',
                'CHARACTER_MAXIMUM_LENGTH': 255,
            },
            {
                'TABLE_NAME': 'scan_yield_stats',
                'DATA_TYPE': 'character varying',
                'CHARACTER_MAXIMUM_LENGTH': 255,
            },
        ]

        class Connection:
            def execute(self, query, args=None):
                return _Result(rows=rows)

        db._ensure_scan_yield_scan_id_collation(Connection())

    def test_postgresql_schema_metadata_rejects_scan_id_type_mismatch(self):
        rows = [
            {
                'table_name': 'scan_runs',
                'data_type': 'character varying',
                'character_maximum_length': 255,
            },
            {
                'table_name': 'scan_yield_stats',
                'data_type': 'text',
                'character_maximum_length': None,
            },
        ]

        class Connection:
            def execute(self, query, args=None):
                return _Result(rows=rows)

        with self.assertRaisesRegex(RuntimeError, 'scan_id type mismatch'):
            db._ensure_scan_yield_scan_id_type(Connection())

    def test_bandwidth_migration_is_transactional(self):
        class Connection:
            def __init__(self):
                self.active = False
                self.commits = 0
                self.rollbacks = 0
                self.queries = []

            @contextmanager
            def transaction(self):
                self.active = True
                try:
                    yield self
                except BaseException:
                    self.rollbacks += 1
                    raise
                else:
                    self.commits += 1
                finally:
                    self.active = False

            def execute(self, query, args=None):
                self.assert_active()
                self.queries.append(query)
                if 'SELECT content' in query:
                    return _Result(None)
                return _Result(None)

            def assert_active(self):
                if not self.active:
                    raise AssertionError('migration DML ran outside transaction')

        conn = Connection()
        with patch.object(db, '_describe_table_columns', return_value=set()):
            db._migrate_scanner_bandwidth_to_mbps(conn)

        self.assertEqual(conn.commits, 1)
        self.assertEqual(conn.rollbacks, 0)
        self.assertTrue(any('INSERT INTO config_data' in query for query in conn.queries))

    def test_default_data_is_one_transaction(self):
        class Connection:
            def __init__(self):
                self.active = False
                self.commits = 0
                self.inserts = 0

            @contextmanager
            def transaction(self):
                self.active = True
                try:
                    yield self
                except BaseException:
                    raise
                else:
                    self.commits += 1
                finally:
                    self.active = False

            def execute(self, query, args=None):
                if not self.active:
                    raise AssertionError('default-data write ran outside transaction')
                if query.lstrip().startswith('INSERT'):
                    self.inserts += 1
                return _Result(None)

        conn = Connection()
        with patch.object(db, '_get_conn', return_value=conn):
            db._init_default_data()

        self.assertEqual(conn.commits, 1)
        self.assertEqual(conn.inserts, 3)

    def test_task_snapshot_has_stable_four_task_shape(self):
        leases = [{
            'task_type': 'scan',
            'task_id': 'scan-1',
            'state': 'running',
            'started_at': '2026-08-08 12:00:00',
            'error': None,
        }]

        snapshot = db.get_tasks_snapshot(leases)

        self.assertEqual(set(snapshot), {'test', 'scan', 'ip_scan', 'detection'})
        self.assertEqual(snapshot['scan'], {
            'task_id': 'scan-1',
            'state': 'running',
            'progress': 0,
            'started_at': '2026-08-08 12:00:00',
            'error': '',
        })
        self.assertEqual(snapshot['test']['state'], 'idle')
        self.assertIsNone(snapshot['test']['task_id'])

    def test_close_thread_connection_rolls_back_once_and_is_idempotent(self):
        class Connection:
            _in_transaction = True

            def __init__(self):
                self.rollbacks = 0
                self.closes = 0

            def rollback(self):
                self.rollbacks += 1

            def close(self):
                self.closes += 1

        conn = Connection()
        local = SimpleNamespace(conn=conn)
        with patch.object(db, '_local', local):
            db.close_thread_connection()
            db.close_thread_connection()

        self.assertEqual(conn.rollbacks, 1)
        self.assertEqual(conn.closes, 1)
        self.assertIsNone(local.conn)


if __name__ == '__main__':
    unittest.main()

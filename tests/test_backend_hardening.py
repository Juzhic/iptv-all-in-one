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

    def test_schema_metadata_accepts_uppercase_dict_cursor_keys(self):
        rows = [
            {
                'TABLE_NAME': 'scan_runs',
                'COLUMN_TYPE': 'varchar(255)',
                'CHARACTER_SET_NAME': 'utf8mb4',
                'COLLATION_NAME': 'utf8mb4_general_ci',
            },
            {
                'TABLE_NAME': 'scan_yield_stats',
                'COLUMN_TYPE': 'varchar(255)',
                'CHARACTER_SET_NAME': 'utf8mb4',
                'COLLATION_NAME': 'utf8mb4_general_ci',
            },
        ]

        class Connection:
            def execute(self, query, args=None):
                return _Result(rows=rows)

        db._ensure_scan_yield_scan_id_collation(Connection())

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

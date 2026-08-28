import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask


def _load_sql_consumer_modules_without_web_startup():
    """Load route modules without executing database-backed ``web.__init__``."""
    root = Path(__file__).resolve().parents[1]
    module_names = (
        'web',
        'web.routes',
        'web.routes.params',
        'web.dashboard_service',
        'web.result_gen',
        'web.subscription_cache',
        'web.routes.history',
        'web.routes.subscribe',
    )
    previous = {name: sys.modules.get(name) for name in module_names}

    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module

    try:
        web_package = types.ModuleType('web')
        web_package.__path__ = [str(root / 'web')]
        sys.modules['web'] = web_package

        routes_package = types.ModuleType('web.routes')
        routes_package.__path__ = [str(root / 'web' / 'routes')]
        sys.modules['web.routes'] = routes_package
        web_package.routes = routes_package

        params = load('web.routes.params', root / 'web' / 'routes' / 'params.py')
        dashboard = load('web.dashboard_service', root / 'web' / 'dashboard_service.py')
        result_gen = load('web.result_gen', root / 'web' / 'result_gen.py')
        subscription_cache = load(
            'web.subscription_cache', root / 'web' / 'subscription_cache.py'
        )
        web_package.dashboard_service = dashboard
        web_package.result_gen = result_gen
        web_package.subscription_cache = subscription_cache
        routes_package.params = params

        history = load('web.routes.history', root / 'web' / 'routes' / 'history.py')
        subscribe = load('web.routes.subscribe', root / 'web' / 'routes' / 'subscribe.py')
        return history, subscribe
    finally:
        for name in reversed(module_names):
            sys.modules.pop(name, None)
            if previous[name] is not None:
                sys.modules[name] = previous[name]


_HISTORY, _SUBSCRIBE = _load_sql_consumer_modules_without_web_startup()


class _Result:
    def __init__(self, one=None, many=None):
        self._one = one
        self._many = many or []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._many


class PostgreSQLSQLConsumerTests(unittest.TestCase):
    def test_priority_update_uses_digest_index_and_original_url_check(self):
        source = (
            Path(__file__).resolve().parents[1] / 'web' / 'routes' / 'scan.py'
        ).read_text(encoding='utf-8')

        self.assertIn("digest(url, 'sha256') = digest(%s, 'sha256')", source)
        self.assertIn('AND url = %s', source)
        self.assertNotIn(
            'UPDATE persistent_scan_results SET priority = %s WHERE url = %s',
            source,
        )

    def test_filtered_subscription_quotes_mixed_case_bandwidth_column(self):
        class Connection:
            def __init__(self):
                self.queries = []

            def execute(self, sql, params=None):
                self.queries.append((sql, params))
                if 'FROM runs' in sql:
                    return _Result(one={'run_id': 'run-1'})
                return _Result(many=[{
                    'channel': 'CCTV-1',
                    'url': 'https://example.test/live',
                    'bandwidth_MBps': 2.5,
                    'connection_latency_ms': 30,
                    'quality_score': 4.5,
                    'output_updated_at': '2026-08-28 12:00:00',
                    'is_h265': 1,
                    'codec': 'hevc',
                }])

        connection = Connection()
        with patch('database._get_conn', return_value=connection):
            rows = _SUBSCRIBE._get_passed_results_with_codec('h265', 1.0)

        self.assertEqual(2.5, rows[0]['bandwidth_MBps'])
        sql, params = connection.queries[-1]
        self.assertEqual(['run-1', 1.0], params)
        self.assertIn('SELECT channel, url, "bandwidth_MBps"', sql)
        self.assertIn('COALESCE("bandwidth_MBps", 0) >= %s', sql)
        self.assertNotIn('COALESCE(bandwidth_MBps', sql)

    def test_channel_trend_quotes_mixed_case_bandwidth_column(self):
        class Connection:
            query = None
            params = None

            def execute(self, sql, params=None):
                self.query = sql
                self.params = params
                return _Result(many=[{
                    'run_id': 'run-1',
                    'finished_at': '2026-08-28 12:00:00',
                    'bandwidth_MBps': 3.25,
                    'connection_latency_ms': 20,
                    'quality_score': 5,
                    'resolution': '1920x1080',
                    'codec': 'h264',
                    'passed': 1,
                }])

        app = Flask(__name__)
        connection = Connection()
        with app.test_request_context('/api/channel/CCTV-1/trend?limit=5'), \
             patch('database._get_conn', return_value=connection):
            response = _HISTORY.api_channel_trend('CCTV-1')

        payload = response.get_json()
        self.assertEqual(3.25, payload['data']['trend'][0]['bandwidth_MBps'])
        self.assertEqual(('CCTV-1', 50), connection.params)
        self.assertIn('res."bandwidth_MBps"', connection.query)


if __name__ == '__main__':
    unittest.main()

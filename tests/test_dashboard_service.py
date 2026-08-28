import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


_MODULE_PATH = Path(__file__).resolve().parents[1] / 'web' / 'dashboard_service.py'
_SPEC = importlib.util.spec_from_file_location('dashboard_service_under_test', _MODULE_PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


class DashboardServiceTests(unittest.TestCase):
    def test_source_score_preserves_weighted_definition_and_caps_components(self):
        score = _MODULE.calculate_source_score(
            channels_passed=100,
            channels_total=100,
            template_total=50,
            avg_bandwidth=50,
            avg_quality=10,
        )
        self.assertEqual(100.0, score)
        self.assertEqual(
            30.0,
            _MODULE.calculate_source_score(5, 10, 10, 0, 0),
        )

    def test_source_url_is_masked_by_default_shape(self):
        masked = _MODULE.mask_source_url('https://user:secret@example.com:8443/private/list.m3u?token=abc')
        self.assertEqual('https://example.com:8443/•••', masked)
        self.assertNotIn('secret', masked)
        self.assertNotIn('token', masked)

    def test_candidate_pool_label_is_not_masked_and_legacy_label_is_normalized(self):
        self.assertEqual(
            '候选源池 · Quake 360',
            _MODULE.mask_source_url('候选源池 · Quake 360'),
        )
        self.assertEqual(
            '候选源池 · 未标注平台',
            _MODULE.mask_source_url('候选源池 · 未标注平台'),
        )
        self.assertEqual(
            '候选源池 · Quake 360',
            _MODULE.mask_source_url('扫描结果池 · Quake 360'),
        )

    def test_sources_page_uses_bound_parameters_for_score_sort(self):
        class Result:
            def __init__(self, one=None, many=None):
                self.one = one
                self.many = many or []

            def fetchone(self):
                return self.one

            def fetchall(self):
                return self.many

        class Connection:
            def execute(self, sql, params=None):
                self.queries.append(sql)
                params = list(params or [])
                self.assert_placeholder_count(sql, params)
                if 'FROM runs ORDER BY' in sql:
                    return Result({'run_id': 'r1', 'finished_at': '2026-08-08 10:00:00'})
                if sql.lstrip().startswith('SELECT COUNT(*)'):
                    return Result({'cnt': 1})
                return Result(many=[{
                    'source_url': 'https://example.com/feed',
                    'channels_total': 10,
                    'channels_passed': 8,
                    'pass_rate': .8,
                    'avg_bandwidth': 2,
                    'avg_quality': 4,
                    'h265_ratio': .25,
                    'score': 76,
                }])

            def assert_placeholder_count(self, sql, params):
                if sql.count('%s') != len(params):
                    raise AssertionError((sql.count('%s'), len(params)))

        connection = Connection()
        connection.queries = []
        with patch.object(_MODULE.db, '_get_conn', return_value=connection), \
             patch.object(_MODULE.db, 'get_config_data', return_value='CCTV-1\nCCTV-2'):
            page = _MODULE.get_sources_page(search='example', sort_by='score')
        self.assertEqual(1, page['total'])
        self.assertEqual('https://example.com/•••', page['items'][0]['source_url'])
        self.assertTrue(any(
            "digest(psr.url, 'sha256') = digest(rr.url, 'sha256')" in sql
            and 'psr.url = rr.url' in sql
            for sql in connection.queries
        ))
        sql = '\n'.join(connection.queries)
        self.assertIn('source_url ILIKE %s', sql)
        self.assertIn('"bandwidth_MBps"', sql)
        self.assertIn('::DOUBLE PRECISION', sql)
        self.assertIn('NULLS LAST', sql)
        self.assertIn("'\u5019\u9009\u6e90\u6c60 \u00b7 ' ||", sql)
        self.assertNotIn('CONCAT(', sql)

    def test_dashboard_queries_preserve_mixed_case_bandwidth_alias(self):
        class Result:
            def __init__(self, one=None, many=None):
                self.one = one
                self.many = many or []

            def fetchone(self):
                return self.one

            def fetchall(self):
                return self.many

        class Connection:
            def __init__(self):
                self.queries = []

            def execute(self, sql, params=None):
                self.queries.append(sql)
                if 'FROM persistent_scan_results WHERE' in sql:
                    return Result(one={
                        'good': 0,
                        'poor': 0,
                        'unreachable': 0,
                        'pending': 0,
                        'avg_stability': None,
                        'avg_delay_ms': None,
                        'avg_bandwidth_MBps': 1.25,
                    })
                return Result(many=[])

        connection = Connection()
        dashboard = _MODULE._scan_dashboard(connection, 10)
        self.assertEqual(1.25, dashboard['pool']['avg_bandwidth_MBps'])
        self.assertIn(
            'AVG(bandwidth) AS "avg_bandwidth_MBps"',
            '\n'.join(connection.queries),
        )


if __name__ == '__main__':
    unittest.main()

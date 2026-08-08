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
        with patch.object(_MODULE.db, '_get_conn', return_value=connection), \
             patch.object(_MODULE.db, 'get_config_data', return_value='CCTV-1\nCCTV-2'):
            page = _MODULE.get_sources_page(search='example', sort_by='score')
        self.assertEqual(1, page['total'])
        self.assertEqual('https://example.com/•••', page['items'][0]['source_url'])


if __name__ == '__main__':
    unittest.main()

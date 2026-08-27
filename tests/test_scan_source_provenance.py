import unittest
from unittest.mock import patch

import database.db as db


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class ScanSourceProvenanceTests(unittest.TestCase):
    def test_persistent_scan_items_keep_platform_provenance_for_testing(self):
        class Connection:
            query = ''

            def execute(self, sql, params=None):
                self.query = sql
                return _Result([
                    {'name': 'CCTV-1', 'url': 'http://quake.example/live', 'platform': 'Quake 360'},
                    {'name': 'CCTV-2', 'url': 'http://unknown.example/live', 'platform': '未知'},
                    {'name': 'CCTV-3', 'url': 'http://blank.example/live', 'platform': None},
                ])

        connection = Connection()
        with patch.object(db, '_get_conn', return_value=connection):
            items = db.get_persistent_for_test()

        self.assertIn('SELECT name, url, platform', connection.query)
        self.assertEqual(
            [
                ({'name': 'CCTV-1', 'source_url': '候选源池 · Quake 360'}, 'http://quake.example/live'),
                ({'name': 'CCTV-2', 'source_url': '候选源池 · 未标注平台'}, 'http://unknown.example/live'),
                ({'name': 'CCTV-3', 'source_url': '候选源池 · 未标注平台'}, 'http://blank.example/live'),
            ],
            items,
        )

    def test_legacy_scan_pool_label_is_normalized_for_display(self):
        self.assertEqual(
            '候选源池 · Hunter',
            db.normalize_scan_source_label('扫描结果池 · Hunter'),
        )


if __name__ == '__main__':
    unittest.main()

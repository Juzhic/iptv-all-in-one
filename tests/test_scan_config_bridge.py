import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / 'scanner_integration' / 'config_bridge.py'
SPEC = importlib.util.spec_from_file_location('scan_config_bridge_under_test', MODULE_PATH)
config_bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(config_bridge)


class SearchKeywordConfigTests(unittest.TestCase):
    def test_platform_queries_use_platform_specific_fields(self):
        queries = config_bridge.build_search_queries({
            'search_keywords': ['title:IPTV', '/iptv/live/ && key=txiptv'],
        })

        self.assertIn('title:"IPTV"', queries['quake'])
        self.assertIn('web.title:"IPTV"', queries['hunter'])
        self.assertIn('title="IPTV"', queries['fofa'])
        self.assertIn('(body="/iptv/live/" && body="key=txiptv")', queries['quake'])
        self.assertIn('(web.body="/iptv/live/" && web.body="key=txiptv")', queries['hunter'])

    def test_keywords_are_trimmed_deduplicated_and_comments_are_ignored(self):
        cfg = config_bridge._normalize_scan_config({
            'search_keywords': [' /iptv/live/zh_cn.js ', '# disabled', '/iptv/live/zh_cn.js'],
        })

        self.assertEqual(['/iptv/live/zh_cn.js'], cfg['search_keywords'])

    def test_empty_keywords_fall_back_to_defaults(self):
        cfg = config_bridge._normalize_scan_config({'search_keywords': []})

        self.assertEqual(config_bridge.DEFAULT_SEARCH_KEYWORDS, cfg['search_keywords'])


if __name__ == '__main__':
    unittest.main()

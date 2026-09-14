import unittest

from scanner_integration import config_bridge


class SearchKeywordConfigTests(unittest.TestCase):
    def test_complete_legacy_defaults_upgrade_but_custom_rules_survive(self):
        legacy = config_bridge.LEGACY_DEFAULT_SEARCH_KEYWORDS
        for rules in (legacy, [*legacy, '/iptv/live/1000.json?key=txiptv']):
            cfg = config_bridge._normalize_scan_config({'search_keywords': list(reversed(rules))})
            self.assertEqual(config_bridge.DEFAULT_SEARCH_KEYWORDS, cfg['search_keywords'])
            query = config_bridge.build_search_queries(cfg)['hunter']
            self.assertIn('web.body="/tsfile/live/"', query)
            self.assertNotIn('key=txiptv', query)
            self.assertIn('web.title="Tvheadend"', query)
            self.assertIn('web.body="/api/live/channels"', query)
        for rules in (legacy[:2], [*legacy, 'title:自定义直播']):
            cfg = config_bridge._normalize_scan_config({'search_keywords': rules})
            self.assertEqual(rules, cfg['search_keywords'])

    def test_channel_list_profile_is_added_to_old_defaults_only(self):
        cfg = config_bridge._normalize_scan_config({
            'quality_query_profiles': ['txiptv_live', 'live_interface', 'zhgx', 'tvheadend'],
        })
        self.assertIn('channel_list', cfg['quality_query_profiles'])
        cfg = config_bridge._normalize_scan_config({'quality_query_profiles': ['zhgx']})
        self.assertEqual(['zhgx'], cfg['quality_query_profiles'])

    def test_platform_queries_use_platform_specific_fields(self):
        queries = config_bridge.build_search_queries({
            'search_keywords': ['title:IPTV', '/iptv/live/ && key=txiptv'],
        })

        self.assertIn('title:"IPTV"', queries['quake'])
        self.assertIn('web.title="IPTV"', queries['hunter'])
        self.assertIn('title="IPTV"', queries['fofa'])
        self.assertIn('(body:"/iptv/live/" AND body:"key=txiptv")', queries['quake'])
        self.assertIn('(web.body="/iptv/live/" && web.body="key=txiptv")', queries['hunter'])

    def test_keywords_are_trimmed_deduplicated_and_comments_are_ignored(self):
        cfg = config_bridge._normalize_scan_config({
            'search_keywords': [' /iptv/live/zh_cn.js ', '# disabled', '/iptv/live/zh_cn.js'],
        })

        self.assertEqual(['/iptv/live/zh_cn.js'], cfg['search_keywords'])

    def test_empty_keywords_fall_back_to_defaults(self):
        cfg = config_bridge._normalize_scan_config({'search_keywords': []})

        self.assertEqual(config_bridge.DEFAULT_SEARCH_KEYWORDS, cfg['search_keywords'])

    def test_legacy_bandwidth_threshold_is_converted_to_mbps(self):
        cfg = config_bridge._normalize_scan_config({
            'quality_thresholds': {'min_bandwidth_kbps': 300},
        })

        self.assertNotIn('min_bandwidth_kbps', cfg['quality_thresholds'])
        self.assertAlmostEqual(
            300 / 1024,
            cfg['quality_thresholds']['min_bandwidth_MBps'],
            places=4,
        )


if __name__ == '__main__':
    unittest.main()

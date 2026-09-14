"""Offline integration checks for the saved settings → execution boundary."""
import asyncio
import base64
import json
import unittest
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

from test_fofa_api import Response, Session, scan_routes
import database
import scanner_integration as scanner
from scanner_integration import config_bridge as config
from scanner_integration.key_manager import KeyManager, check_hunter_credit, _credit_is_usable
from scanner_integration.platforms import collector, hunter
from scanner_integration.platforms.shared import KeyDepletedError
from scanner_integration.hunter_api import read_hunter_response
from scanner_integration.community_sources import scan_community_sources
from scanner_integration.video_check import get_deep_check_options
from flask import Flask


class HunterContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_account_does_not_fallback_to_search_and_keeps_failure_origin(self):
        session = Session(Response({'code': 400, 'message': 'account denied secret'}, 403))
        result = await check_hunter_credit('secret', session)
        self.assertEqual(1, len(session.calls))
        self.assertTrue(session.calls[0][0].endswith('/openApi/userInfo'))
        self.assertIn('userInfo HTTP 403', result['error'])
        self.assertNotIn('secret', result['error'])
        self.assertNotIn('points', result)

    async def test_paid_balance_is_not_hidden_by_zero_free_points(self):
        session = Session(Response({'code': '200', 'data': {
            'rest_free_point': 0, 'rest_equity_point': 120,
            'personal_info': {'username': 'example'},
        }}))
        info = await check_hunter_credit('key', session)
        self.assertEqual(120, info['points'])
        self.assertEqual('example', info['role'])
        self.assertTrue(_credit_is_usable(info['points']))

    async def test_unknown_and_unlimited_pools_remain_usable(self):
        for pools, expected in (({'rest_free_point': 0}, None),
                                ({'rest_free_point': -1}, -1),
                                ({'rest_free_point': 0, 'rest_equity_point': 0}, 0)):
            info = await check_hunter_credit('key', Session(Response({'code': 200, 'data': pools})))
            self.assertEqual(expected, info['points'])
        self.assertTrue(_credit_is_usable(-1))

    async def test_permission_is_not_quota_exhaustion(self):
        with self.assertRaises(ValueError):
            await read_hunter_response(Response({'message': '账号无 API 访问权限'}, 403), 'search')
        with self.assertRaises(KeyDepletedError):
            await read_hunter_response(Response({'code': 400, 'message': '积分不足'}), 'search')

    async def test_search_pagination_neither_repeats_offsets_nor_exceeds_target(self):
        class Pages(Session):
            def get(self, url, **kwargs):
                self.calls.append((url, kwargs))
                page, size = kwargs['params']['page'], kwargs['params']['page_size']
                return Response({'code': '200', 'data': {'arr': [
                    {'ip': f'192.0.2.{i + 1}', 'port': 80}
                    for i in range((page - 1) * size, page * size)
                ]}})
        session = Pages()
        extract = AsyncMock(return_value=[])
        with patch.object(config, 'get_scan_config', return_value={'enable_c_scan': False}), \
             patch.object(hunter, 'extract_channels_from_ip', extract), \
             patch('asyncio.sleep', new_callable=AsyncMock):
            await hunter.hunter_scan('key', 'web.title="电视"', 15, session=session)
        params = [call[1]['params'] for call in session.calls]
        self.assertEqual([10, 5], [p['page_size'] for p in params])
        self.assertEqual([1, 3], [p['page'] for p in params])
        self.assertEqual('web.title="电视"', base64.urlsafe_b64decode(params[0]['search']).decode())
        self.assertEqual(15, len({call.args[0] for call in extract.call_args_list}))


class SavedConfigurationTests(unittest.IsolatedAsyncioTestCase):
    async def test_recommended_channel_lists_and_tvheadend_are_actually_extracted(self):
        from scanner_integration.platforms import ip_extract
        paths = [*config.CHANNEL_LIST_SEARCH_KEYWORDS, '/playlist?profile=pass']
        for path in paths:
            with self.subTest(path=path):
                session = Session()
                def get(url, **kwargs):
                    session.calls.append((url, kwargs))
                    response = Response({}, 200 if url.endswith(path) else 404)
                    response.url = url
                    return response
                session.get = get
                raw = (b'#EXTM3U\n#EXTINF:-1,CCTV1\n/stream/channel/1\n'
                       if path.startswith('/playlist') else
                       b'{"channels":[{"name":"CCTV1","url":"/tsfile/live/1.m3u8"}]}')
                with patch.object(ip_extract, '_get_extract_cache', return_value=None), \
                     patch.object(ip_extract, '_set_extract_cache'), \
                     patch.object(ip_extract, 'read_response_limited', new_callable=AsyncMock, return_value=raw):
                    entries = await ip_extract.extract_channels_from_ip('8.8.8.8', 8080, session)
                self.assertEqual(1, len(entries))
                self.assertTrue(entries[0]['url'].startswith('http://8.8.8.8:8080/'))
                self.assertTrue(session.calls[-1][0].endswith(path))

    async def test_save_reload_and_task_snapshot_propagate_to_deep_check(self):
        store = {'raw': '{}'}
        def write(key, raw):
            store['raw'] = raw
        with patch.object(database, 'get_config_data_with_mtime', side_effect=lambda key: (store['raw'], 'same-second')), \
             patch.object(database, 'set_config_data', side_effect=write), \
             patch.object(config, '_CONFIG_CACHE', None):
            config.save_scan_config({'deep_check_duration': 17, 'enabled_platforms': ['hunter'],
                                     'daily_full_update': False, 'update_days': [],
                                     'search_keywords': ['title:直播']})
            self.assertEqual(17, config.get_scan_config()['deep_check_duration'])
            self.assertEqual([], config.get_scan_config()['update_days'])
            self.assertIn('web.title="直播"', config.build_search_queries()['hunter'])
            @config.scan_config_snapshot
            async def run():
                config.save_scan_config({'deep_check_duration': 25})
                read = config.get_scan_config()
                read['enabled_platforms'].clear()
                self.assertEqual(['hunter'], config.get_scan_config()['enabled_platforms'])
                self.assertEqual(17, get_deep_check_options()['duration'])
            await run()
            self.assertEqual(25, config.get_scan_config()['deep_check_duration'])

    async def test_blank_proxy_and_community_switch_are_obeyed(self):
        for enabled in (False, True):
            with patch.object(config, 'get_scan_config', return_value={
                'community_sources_enabled': enabled, 'github_proxy': '',
                'community_source_urls': ['https://example.com/list.m3u'],
            }), patch('scanner_integration.community_sources.fetch_community_m3u', new_callable=AsyncMock, return_value=[]) as fetch, \
                 patch('scanner_integration.community_sources._detect_github_proxy', new_callable=AsyncMock) as detect:
                await scan_community_sources(session=Session())
                detect.assert_not_called()
                if enabled:
                    self.assertIn('https://example.com/list.m3u', [c.args[1] for c in fetch.call_args_list])
                else:
                    fetch.assert_not_called()

    async def test_quality_budget_and_platform_filters_reach_real_planner(self):
        km = KeyManager()
        km.load_keys('quake', ['q'])
        km.load_keys('hunter', ['h'])
        cfg = config._normalize_scan_config({
            'enabled_platforms': ['quake'], 'selected_provinces': ['浙江', '江苏', '广东', '广西'],
            'operator': '电信', 'quake_size': 23, 'quality_query_profile_size': 10,
            'quality_discovery_platforms': ['quake'], 'cost_saver_mode': True,
        })
        with patch.object(config, 'get_scan_config', return_value=cfg), \
             patch.object(KeyManager, 'instance', return_value=km), \
             patch.object(collector, 'get_session', return_value=Session()), \
             patch.object(collector, 'quake_scan', new_callable=AsyncMock, return_value=[]) as quake, \
             patch.object(collector, 'hunter_scan', new_callable=AsyncMock) as hunter_scan, \
             patch('scanner_integration.domain_ip_scanner.domain_ip_scan', new_callable=AsyncMock) as domains:
            await collector.collect_all()
            calls = quake.call_args_list
            self.assertEqual([23] * 4, [c.args[2] for c in calls[:4]])
            self.assertEqual(10, sum(c.args[2] for c in calls[4:]))
            self.assertTrue(any('/channel_list.json' in c.args[1] for c in calls[4:]))
            self.assertIn('AND province_cn:"浙江"', calls[0].args[1])
            self.assertIn('AND isp:"电信"', calls[0].args[1])
            hunter_scan.assert_not_called()
            domains.assert_not_called()
            # An explicit discovery platform outside the selection must not fall back.
            cfg['quality_discovery_platforms'] = ['hunter']
            quake.reset_mock()
            await collector.collect_all()
            self.assertEqual(4, quake.call_count)

    async def test_incremental_executes_enabled_supplemental_sources(self):
        with ExitStack() as stack:
            for name in ('clear_scan_logs', 'insert_scan_run', 'update_scan_progress', 'update_scan_run', 'clear_scan_progress'):
                stack.enter_context(patch.object(database, name))
            stack.enter_context(patch.object(database, 'get_all_persistent_for_check', return_value=[]))
            for name in ('_scan_log', '_broadcast_sse', '_broadcast_scan_status'):
                stack.enter_context(patch.object(scanner, name))
            cfg = {'quality_hotspot_enabled': False, 'isp_intelligence_enabled': True, 'community_sources_enabled': True}
            stack.enter_context(patch.object(config, 'get_scan_config', return_value=cfg))
            stack.enter_context(patch('scanner_integration.platforms.collect_all', new_callable=AsyncMock, return_value=([], [], [])))
            stack.enter_context(patch('scanner_integration.network.get_session', return_value=Session()))
            hot = stack.enter_context(patch('scanner_integration.isp_intelligence.scan_hot_segments', new_callable=AsyncMock, return_value=[]))
            community = stack.enter_context(patch('scanner_integration.community_sources.scan_community_sources', new_callable=AsyncMock, return_value=[]))
            await scanner._do_incremental_scan()
            hot.assert_awaited_once()
            community.assert_awaited_once()
            cfg.update(isp_intelligence_enabled=False, community_sources_enabled=False)
            hot.reset_mock(); community.reset_mock()
            await scanner._do_incremental_scan()
            hot.assert_not_called(); community.assert_not_called()

    def test_failed_config_read_is_not_reported_as_successful_defaults(self):
        app = Flask(__name__)
        app.register_blueprint(scan_routes.scan_bp)
        with patch.object(scan_routes, '_get_scanner', return_value=None), \
             patch.object(config, 'get_scan_config', side_effect=RuntimeError('offline')):
            response = app.test_client().get('/api/scan/config')
        self.assertEqual(503, response.status_code)
        self.assertFalse(response.json['ok'])

    def test_corrupt_stored_json_cannot_be_overwritten_with_defaults(self):
        with patch.object(database, 'get_config_data_with_mtime', return_value=('{broken', 'now')), \
             patch.object(database, 'set_config_data') as write:
            with self.assertRaises(ValueError):
                config.save_scan_config({'hunter_size': 20})
            write.assert_not_called()

    def test_normalized_profiles_always_have_an_implemented_query(self):
        implemented = {p['name'] for p in collector.QUALITY_QUERY_PROFILES}
        for profiles in (['xtream'], ['tvheadend', 'xtream'], config.LEGACY_DEFAULT_QUALITY_PROFILE_NAMES):
            cfg = config._normalize_scan_config({'quality_query_profiles': profiles})
            self.assertTrue(cfg['quality_query_profiles'])
            self.assertTrue(set(cfg['quality_query_profiles']) <= implemented)

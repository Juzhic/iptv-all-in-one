"""Offline UDPXY integration checks: no live proxies, keys or database required."""
import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from test_fofa_api import Response, Session, scan_routes, load_scan_routes
from flask import Flask
from scanner_integration import config_bridge as config
from scanner_integration.multicast_templates import (
    builtin_catalog, builtin_templates, multicast_address, normalize_proxy_url,
    parse_manual_proxies, parse_playlist, selected_templates, validate_config,
)
from scanner_integration.platforms import collector, udpxy
from scanner_integration.platforms import ip_extract, quake, fofa, hunter, daydaymap
from scanner_integration.ip_scanner import IPScanner
from scanner_integration.safe_http import SafeResponse


def settings(**overrides):
    return config._normalize_scan_config({
        'multicast_enabled': True, 'multicast_quake_enabled': False,
        'multicast_use_builtin': False, 'multicast_templates': [{
            'province': '广东', 'operator': '电信',
            'content': 'CCTV1,rtp://239.1.1.1:1234\nCCTV2,udp://239.1.1.2:1234\n广东卫视,rtp://239.1.1.3:1234',
        }],
        'multicast_proxy_urls': '广东,电信,http://8.8.8.8:4022',
        'cost_saver_mode': True, 'quality_discovery_enabled': False, 'enable_c_scan': False,
        **overrides,
    })


class TemplateTests(unittest.TestCase):
    def test_txt_and_m3u_extract_destinations_without_old_hosts_or_ads(self):
        txt = '\n'.join([
            '广告,https://example.com/ad.m3u8', '分类,#genre#',
            'CCTV1,http://old-proxy.invalid:80/rtp/239.1.1.1:1234',
            '重复,rtp://239.1.1.1:1234',
            'CCTV2,udp://@239.1.1.2:1234$线路1#rtp://239.1.1.3:1234',
            '无效,rtp://127.0.0.1:1234', '无效,rtp://239.1.1.4:0',
            '无效,rtp://239.1.1.4:1234;echo injected',
        ])
        rows = parse_playlist(txt)
        self.assertEqual(3, len(rows))
        self.assertEqual({'name': 'CCTV1', 'protocol': 'rtp', 'address': '239.1.1.1:1234'}, rows[0])
        self.assertNotIn('old-proxy', json.dumps(rows))
        m3u = '\ufeff#EXTM3U\n#EXTINF:-1 group-title="组播",CCTV1\n#EXTVLCOPT:test=1\nrtp://239.1.1.1:1234\n'
        self.assertEqual(rows[:1], parse_playlist(m3u))
        self.assertEqual([], parse_playlist('<html><title>Not Found</title></html>'))

    def test_address_and_proxy_boundaries(self):
        for value in ('rtp://239.1.1.1:65536', 'rtp://239.999.1.1:80', 'rtp://1.1.1.1:80', 'file:///rtp/239.1.1.1:80'):
            self.assertIsNone(multicast_address(value))
        for value in ('http://127.0.0.1', 'http://10.0.0.1:80', 'http://169.254.169.254',
                      'http://example.com', 'http://user:pass@8.8.8.8', 'http://8.8.8.8?key=x',
                      'http://8.8.8.8/rtp/239.1.1.1:80', 'http://8.8.8.8/../status',
                      'http://8.8.8.8:0', 'http://[::ffff:127.0.0.1]', 'http://239.1.1.1',
                      'http://8.8.8.8/#x', 'http://8.8.8.8/%2e%2e', 'http://168.63.129.16',
                      'http://[::ffff:168.63.129.16]'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_proxy_url(value)
        self.assertEqual('https://8.8.8.8:443/udpxy', normalize_proxy_url('https://8.8.8.8/udpxy/'))
        self.assertEqual('http://[2606:4700:4700::1111]:80', normalize_proxy_url('http://[2606:4700:4700::1111]'))

    def test_manual_proxies_normalize_and_deduplicate(self):
        proxies = parse_manual_proxies('# comment\n广东省,中国电信,http://8.8.8.8\n广东,电信,http://8.8.8.8:80/')
        self.assertEqual(1, len(proxies))
        self.assertEqual('广东', proxies[0]['province'])
        for text in ('广东,其他,http://8.8.8.8', '未知,电信,http://8.8.8.8', 'http://8.8.8.8'):
            with self.assertRaises(ValueError):
                parse_manual_proxies(text)

    def test_custom_template_replaces_only_its_matching_group(self):
        cfg = settings(multicast_use_builtin=True)
        groups = selected_templates(cfg, ['广东省'])
        self.assertEqual(3, len(groups[('广东', '电信')]['channels']))
        self.assertEqual('custom', groups[('广东', '电信')]['source'])
        self.assertIn(('广东', '联通'), groups)
        self.assertEqual({('广东', '电信')}, set(selected_templates({**cfg, 'operator': '电信'}, ['广东'])))
        self.assertEqual({}, selected_templates(cfg, ['未知省份']))
        self.assertEqual({}, selected_templates({**cfg, 'operator': '未知运营商'}, []))
        self.assertEqual({}, selected_templates(settings(), ['浙江']))

    def test_validation_rejects_bad_templates_and_preserves_limits(self):
        validate_config(settings())
        for update in ({'multicast_enabled': 'false'}, {'multicast_max_proxies': 0},
                       {'multicast_max_channels': True},
                       {'multicast_templates': [{}]}, {'multicast_templates': 'invalid'},
                       {'multicast_templates': settings()['multicast_templates'] * 2},
                       {'multicast_templates': [{'province': '广东', 'operator': '电信', 'content': 'CCTV1,https://example.com/a.m3u8'}]}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                validate_config(update)
        self.assertFalse(config._normalize_scan_config({})['multicast_enabled'])
        self.assertEqual(50, config._normalize_scan_config({'multicast_max_proxies': 999})['multicast_max_proxies'])

    def test_vendored_templates_have_only_unique_multicast_destinations(self):
        catalog = builtin_catalog()
        self.assertEqual(36, len(catalog))
        self.assertGreater(sum(group['channels'] for group in catalog), 7000)
        for group in builtin_templates():
            urls = [f"{row['protocol']}://{row['address']}" for row in group['channels']]
            self.assertEqual(len(urls), len(set(urls)))
            self.assertTrue(all(multicast_address(url) for url in urls))


class MulticastRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stop = patch.object(udpxy, '_is_stop_requested', return_value=False)
        self.stop.start()
        self.addCleanup(self.stop.stop)
        self.log = MagicMock()

    async def playable(self, proxy, *args):
        return {**proxy, 'active_clients': None}

    async def test_shared_limits_deduplication_round_robin_and_provenance(self):
        cfg = settings(multicast_max_proxies=2, multicast_max_channels=3)
        discovery = udpxy.MulticastDiscovery(cfg, ['广东'])
        with udpxy.discovery_source('Fofa', 'fofa-main', '广东'):
            discovery.add('http://8.8.8.8:4022')
            discovery.add('http://8.8.8.8:4022')
        with udpxy.discovery_source('Hunter', 'hunter-main', '广东'):
            discovery.add('http://1.1.1.1:4022')
            discovery.add('http://9.9.9.9:4022')
        with patch.object(udpxy, 'probe_proxy', side_effect=self.playable) as probe:
            channels = await discovery.finish(Session())
        self.assertEqual(2, probe.call_count)
        self.assertEqual(3, len(channels))
        self.assertEqual(['Fofa', 'Hunter', 'Fofa'], [row['platform'] for row in channels])
        self.assertEqual(['fofa-main', 'hunter-main', 'fofa-main'], [row['yield_stat_key'] for row in channels])
        self.assertTrue(all('bandwidth' not in row and 'stability' not in row for row in channels))

    async def test_all_platform_adapters_use_common_udpxy_extraction(self):
        adapters = [
            ('Quake 360', quake.quake_scan, {'code': 0, 'data': [{'ip': '8.8.8.8', 'port': 4022}]}),
            ('Hunter', hunter.hunter_scan, {'code': 200, 'data': {'arr': [{'ip': '8.8.8.8', 'port': 4022}]}}),
            ('DayDayMap', daydaymap.daydaymap_scan, {'code': 200, 'data': {'list': [{'ip': '8.8.8.8', 'port': 4022}]}}),
            ('Fofa', fofa.fofa_scan, {}),
        ]
        for name, adapter, payload in adapters:
            with self.subTest(platform=name):
                cfg = settings(enable_c_scan=False)
                session = Session(Response(payload))
                session.post = session.get
                with patch.object(config, 'get_scan_config', return_value=cfg), \
                     patch.object(fofa, 'request_fofa', new_callable=AsyncMock,
                                  return_value={'results': [['8.8.8.8', 4022, '广东', '广州']]}), \
                     patch('asyncio.sleep', new_callable=AsyncMock), \
                     patch.object(udpxy, 'probe_proxy', side_effect=self.playable):
                    with udpxy.multicast_run(cfg, ['广东']) as discovery:
                        with udpxy.discovery_source(name, name, '广东', udpxy_only=True):
                            stats = {}
                            await adapter('test-key', 'query', 1, session=session, stats=stats)
                        channels = await discovery.finish(session)
                self.assertEqual(1, stats['api_items'])
                self.assertEqual(3, len(channels))
                self.assertTrue(all(row['platform'] == name for row in channels))
                self.assertTrue(all(row['province'] == '广东' for row in channels))

    async def test_regular_extraction_recognizes_status_even_with_cached_empty_result(self):
        response = SafeResponse(200, {}, b'<title>udpxy status</title>', 'http://8.8.8.8/status', '8.8.8.8', 1)
        with udpxy.multicast_run(settings(), ['广东']) as discovery, \
             udpxy.discovery_source('Quake 360', 'quake-main'), \
             patch.object(ip_extract, '_get_extract_cache', return_value=[]), \
             patch.object(udpxy, 'safe_fetch', new_callable=AsyncMock, return_value=response) as fetch:
            await ip_extract.extract_channels_from_ip('8.8.8.8', 4022, Session(), '广东', operator='中国电信')
            await ip_extract.extract_channels_from_ip('8.8.8.8', 4022, Session(), '广东')
        self.assertEqual(1, fetch.call_count)
        self.assertEqual(1, len(discovery.proxies))
        self.assertFalse(fetch.call_args.kwargs['max_redirects'])

    async def test_disabled_unknown_region_filtered_region_and_private_hosts_do_not_expand(self):
        templates = settings()['multicast_templates']
        templates.append({**templates[0], 'province': '浙江'})
        for cfg, provinces, address, province in (
            (settings(multicast_enabled=False), [], 'http://8.8.8.8', '广东'),
            (settings(), ['浙江'], 'http://8.8.8.8', '广东'),
            (settings(), ['广东'], 'http://127.0.0.1', '广东'),
            (settings(multicast_templates=templates), [], 'http://8.8.8.8', ''),
        ):
            discovery = udpxy.MulticastDiscovery(cfg, provinces)
            discovery.add(address, province)
            with patch.object(udpxy, 'probe_proxy', side_effect=self.playable) as probe:
                self.assertEqual([], await discovery.finish(Session()))
                probe.assert_not_called()

    async def test_status_page_failure_still_checks_bounded_stream_samples(self):
        proxy = parse_manual_proxies(settings()['multicast_proxy_urls'])[0]
        template = next(iter(selected_templates(settings(), []).values()))
        status = SafeResponse(404, {}, b'', proxy['url'] + '/status', '8.8.8.8', 1)
        with patch.object(udpxy, 'safe_fetch', new_callable=AsyncMock, return_value=status) as fetch, \
             patch.object(udpxy, '_stream_sample', new_callable=AsyncMock, side_effect=[False, True]) as sample:
            result = await udpxy.probe_proxy(proxy, template, Session(), asyncio.Semaphore(1))
        self.assertIsNotNone(result)
        self.assertEqual(2, sample.call_count)
        self.assertEqual(0, fetch.call_args.kwargs['max_redirects'])

    async def test_http_200_html_is_not_playable_and_stream_reads_are_bounded(self):
        for data, expected in ((b'<html>ok</html>' * 150, False), ((b'\x47' + bytes(187)) * 7, True)):
            response = Response({})
            response.content = MagicMock()
            response.content.readexactly = AsyncMock(return_value=data)
            session = Session(response)
            self.assertEqual(expected, await udpxy._stream_sample(session, 'http://8.8.8.8/rtp/239.1.1.1:80'))
            response.content.readexactly.assert_awaited_once_with(1316)
            self.assertFalse(session.calls[0][1]['allow_redirects'])

    async def test_timeout_keeps_verified_proxies_and_cancels_pending_probes(self):
        discovery = udpxy.MulticastDiscovery(settings(), ['广东'])
        for host in ('8.8.8.8', '1.1.1.1'):
            discovery.add('http://' + host)
        cancelled = asyncio.Event()
        async def probe(proxy, *args):
            if '8.8.8.8' in proxy['url']:
                return {**proxy, 'active_clients': 0}
            try:
                await asyncio.sleep(10)
            finally:
                cancelled.set()
        with patch.object(udpxy, 'probe_proxy', side_effect=probe), patch.object(udpxy, 'MAX_RUN_SECONDS', 0.02):
            channels = await discovery.finish(Session())
        self.assertEqual(3, len(channels))
        self.assertTrue(cancelled.is_set())

    async def test_stop_suppresses_expansion_and_context_is_reset(self):
        stopped = False
        with udpxy.multicast_run(settings(), ['广东'], stop_requested=lambda: stopped) as discovery:
            discovery.add('http://8.8.8.8')
            stopped = True
            with patch.object(udpxy, 'probe_proxy', side_effect=self.playable) as probe:
                self.assertEqual([], await discovery.finish(Session()))
                probe.assert_not_called()
        self.assertIsNone(udpxy.current_discovery())
        with self.assertRaises(RuntimeError):
            with udpxy.multicast_run(settings(), ['广东']):
                raise RuntimeError('cancelled')
        self.assertIsNone(udpxy.current_discovery())

    async def test_collector_preserves_legacy_manual_proxies_without_search_keys(self):
        manager = MagicMock()
        manager.get_key.return_value = None
        manager.get_all_keys.return_value = []
        with patch('scanner_integration.key_manager.KeyManager.instance', return_value=manager), \
             patch.object(config, 'get_scan_config', return_value=settings()), \
             patch.object(collector, 'get_session', return_value=Session()), \
             patch.object(collector, '_is_stop_requested', return_value=False), \
             patch.object(udpxy, 'probe_proxy', side_effect=self.playable):
            channels, platforms, rows = await collector.collect_all(log_fn=self.log)
        self.assertEqual(3, len(channels))
        self.assertEqual(['udpxy'], platforms)
        self.assertEqual(3, rows[0]['cleaned_channels'])

    async def test_collector_shares_profile_budget_and_updates_platform_yield(self):
        cfg = settings(multicast_proxy_urls='', enabled_platforms=['fofa'], selected_provinces=['广东'],
                       fofa_size=5, quality_discovery_enabled=True, quality_query_profile_size=12)
        manager = MagicMock()
        manager.get_key.side_effect = lambda platform: 'key' if platform == 'fofa' else None
        manager.get_all_keys.side_effect = lambda platform: ['key'] if platform == 'fofa' else []
        async def scan(platform, func, query, target, **kwargs):
            if udpxy.is_udpxy_query():
                await ip_extract.extract_channels_from_ip('8.8.8.8', 4022, Session())
            return []
        with patch('scanner_integration.key_manager.KeyManager.instance', return_value=manager), \
             patch.object(config, 'get_scan_config', return_value=cfg), \
             patch.object(collector, 'get_session', return_value=Session()), \
             patch.object(collector, '_is_stop_requested', return_value=False), \
             patch.object(collector, '_run_with_key_rotation', side_effect=scan) as search, \
             patch.object(udpxy, 'probe_proxy', side_effect=self.playable):
            channels, platforms, rows = await collector.collect_all(log_fn=self.log)
        self.assertEqual(5, search.call_args_list[0].args[3])
        self.assertEqual(12, sum(call.args[3] for call in search.call_args_list[1:]))
        self.assertTrue(all(call.args[0] == 'fofa' for call in search.call_args_list))
        self.assertEqual(['fofa'], platforms)
        self.assertEqual(3, len(channels))
        self.assertTrue(all(row['platform'] == 'Fofa' for row in channels))
        row = next(row for row in rows if row['profile'] == 'udpxy')
        self.assertEqual(3, row['extracted_channels'])
        self.assertEqual(3, row['cleaned_channels'])

    async def test_manual_ip_scan_uses_templates_without_root_page_or_api_keys(self):
        scanner = IPScanner({'scan_config': settings(multicast_enabled=False),
                             'multicast_province': '广东', 'multicast_operator': '电信'})
        with patch.object(udpxy, 'probe_proxy', side_effect=self.playable), \
             patch('scanner_integration.network.get_session', return_value=Session()), \
             patch('scanner_integration.ip_scanner.safe_fetch', new_callable=AsyncMock) as root_fetch:
            results = await scanner.scan_targets('8.8.8.8:4022', ['MULTICAST'], [80])
        root_fetch.assert_not_called()
        self.assertEqual(3, results[0]['channel_count'])
        self.assertTrue(results[0]['alive'])
        self.assertEqual('MULTICAST', results[0]['scan_type_matched'])
        self.assertTrue(all(row['url'].startswith('http://8.8.8.8:4022/')
                            for row in json.loads(results[0]['channels_json'])))

    async def test_broken_proxy_is_isolated_from_other_results(self):
        discovery = udpxy.MulticastDiscovery(settings(), ['广东'])
        discovery.add('http://8.8.8.8')
        discovery.add('http://1.1.1.1')
        async def probe(proxy, *args):
            if '8.8.8.8' in proxy['url']:
                raise RuntimeError('malformed endpoint')
            return {**proxy, 'active_clients': 0}
        with patch.object(udpxy, 'probe_proxy', side_effect=probe):
            channels = await discovery.finish(Session())
        self.assertEqual(3, len(channels))
        self.assertTrue(all(row['source_ip'] == '1.1.1.1' for row in channels))

    async def test_all_manual_scan_obeys_disabled_switch(self):
        scanner = IPScanner({'scan_config': settings(multicast_enabled=False)})
        response = SafeResponse(404, {}, b'', 'http://8.8.8.8/', '8.8.8.8', 1)
        with patch.object(udpxy, 'probe_proxy', side_effect=self.playable) as probe, \
             patch('scanner_integration.network.get_session', return_value=Session()), \
             patch('scanner_integration.ip_scanner.safe_fetch', new_callable=AsyncMock, return_value=response):
            results = await scanner.scan_targets('8.8.8.8:4022', ['ALL'], [80])
        probe.assert_not_called()
        self.assertEqual(0, results[0]['channel_count'])


class MulticastConfigAPITests(unittest.TestCase):
    def test_manual_route_validates_and_passes_template_scope(self):
        ip_scan = load_scan_routes('web.routes.ip_scan')
        app = Flask(__name__)
        app.register_blueprint(ip_scan.ip_scan_bp)
        scanner = MagicMock()
        scanner.trigger_ip_scan.return_value = {'ok': True, 'task': {'task_id': 'test-scan'}}
        with patch.object(ip_scan, '_ensure_ip_scan_bridge', return_value=(scanner, None, None)):
            response = app.test_client().post('/api/ip-scan/trigger', json={
                'targets': '8.8.8.8:4022', 'scan_types': ['MULTICAST'],
                'multicast_province': '广东省', 'multicast_operator': '中国电信',
            })
            self.assertEqual(202, response.status_code)
            self.assertEqual('广东', scanner.trigger_ip_scan.call_args.kwargs['multicast_province'])
            self.assertEqual('电信', scanner.trigger_ip_scan.call_args.kwargs['multicast_operator'])
            scanner.reset_mock()
            response = app.test_client().post('/api/ip-scan/trigger', json={
                'targets': '8.8.8.8:4022', 'multicast_province': '未知省份',
            })
            self.assertEqual(400, response.status_code)
            scanner.trigger_ip_scan.assert_not_called()

    def test_upgrade_removes_independent_search_controls_and_keeps_templates_and_seeds(self):
        cfg = settings(multicast_search_size=60, multicast_quake_enabled=False)
        self.assertNotIn('multicast_search_size', cfg)
        self.assertNotIn('multicast_quake_enabled', cfg)
        self.assertTrue(cfg['multicast_proxy_urls'])
        self.assertTrue(cfg['multicast_templates'])
        for platform, query in config.build_search_queries(cfg).items():
            self.assertIn('udpxy', query)
        for query in config.build_search_queries({**cfg, 'multicast_enabled': False}).values():
            self.assertNotIn('udpxy', query)


    def test_invalid_template_returns_400_without_persisting(self):
        app = Flask(__name__)
        app.register_blueprint(scan_routes.scan_bp)
        with patch.object(config, '_read_scan_config', return_value=config._normalize_scan_config({})), \
             patch('database.set_config_data') as write:
            response = app.test_client().post('/api/scan/config', json={'multicast_templates': [{}]})
        self.assertEqual(400, response.status_code)
        write.assert_not_called()

    def test_configuration_roundtrip_and_public_catalog(self):
        saved = {}
        def write(key, value):
            saved.update(json.loads(value))
        with patch.object(config, '_read_scan_config', return_value=config._normalize_scan_config({})), \
             patch('database.set_config_data', side_effect=write):
            config.save_scan_config(settings())
        cfg = config._normalize_scan_config(saved)
        self.assertEqual(settings()['multicast_templates'], cfg['multicast_templates'])
        self.assertEqual(settings()['multicast_proxy_urls'], cfg['multicast_proxy_urls'])
        public = scan_routes._public_scan_config(cfg)
        self.assertEqual(36, len(public['multicast_builtin_catalog']))
        self.assertNotIn('multicast_builtin_catalog', scan_routes._strip_scan_secret_updates(public))


if __name__ == '__main__':
    unittest.main()

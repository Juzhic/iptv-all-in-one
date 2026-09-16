"""Offline UDPXY integration checks: no live proxies, keys or database required."""
import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from test_fofa_api import Response, Session, scan_routes
from flask import Flask
from scanner_integration import config_bridge as config
from scanner_integration.multicast_templates import (
    builtin_catalog, builtin_templates, multicast_address, normalize_proxy_url,
    parse_manual_proxies, parse_playlist, selected_templates, validate_config,
)
from scanner_integration.platforms import collector, udpxy
from scanner_integration.platforms.shared import KeyDepletedError
from scanner_integration.safe_http import SafeResponse


def settings(**overrides):
    return config._normalize_scan_config({
        'multicast_enabled': True, 'multicast_quake_enabled': False,
        'multicast_use_builtin': False, 'multicast_templates': [{
            'province': '广东', 'operator': '电信',
            'content': 'CCTV1,rtp://239.1.1.1:1234\nCCTV2,udp://239.1.1.2:1234\n广东卫视,rtp://239.1.1.3:1234',
        }],
        'multicast_proxy_urls': '广东,电信,http://8.8.8.8:4022',
        'cost_saver_mode': True, 'quality_discovery_enabled': False,
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
                       {'multicast_max_channels': True}, {'multicast_search_size': float('inf')},
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

    async def test_manual_discovery_is_bounded_and_preserves_source_without_quality(self):
        cfg = settings(multicast_max_proxies=1, multicast_max_channels=2,
                       multicast_proxy_urls='广东,电信,http://8.8.8.8:4022\n广东,电信,http://1.1.1.1:4022')
        async def probe(proxy, *args):
            return {**proxy, 'active_clients': None}
        with patch.object(udpxy, 'probe_proxy', side_effect=probe) as checked, \
             patch.object(collector, '_run_with_key_rotation', new_callable=AsyncMock) as search:
            channels, rows = await udpxy.collect_multicast(cfg, [], ['广东'], session=Session(), log_fn=self.log)
        search.assert_not_called()
        self.assertEqual(1, checked.call_count)
        self.assertEqual(2, len(channels))
        self.assertEqual(2, rows[0]['extracted_channels'])
        self.assertTrue(all(row['platform'] == 'UDPXY' and row['source_ip'] == '8.8.8.8' for row in channels))
        self.assertTrue(all('bandwidth' not in row and 'stability' not in row for row in channels))
        self.assertTrue(all(row['url'].startswith('http://8.8.8.8:4022/') for row in channels))

    async def test_disabled_stopped_or_out_of_scope_never_probes(self):
        for cfg, platforms, provinces in ((settings(multicast_enabled=False), ['quake'], []),
                                           (settings(), [], ['浙江'])):
            with patch.object(udpxy, 'probe_proxy', new_callable=AsyncMock) as probe:
                self.assertEqual(([], []), await udpxy.collect_multicast(cfg, platforms, provinces, session=Session(), log_fn=self.log))
                probe.assert_not_called()
        with patch.object(udpxy, '_is_stop_requested', return_value=True), \
             patch.object(udpxy, 'probe_proxy', new_callable=AsyncMock) as probe:
            channels, _ = await udpxy.collect_multicast(settings(), [], [], session=Session(), log_fn=self.log)
            self.assertEqual([], channels)
            probe.assert_not_called()

    async def test_quake_budget_is_shared_across_groups_and_platform_selection_is_respected(self):
        templates = settings()['multicast_templates']
        templates.append({**templates[0], 'province': '浙江'})
        cfg = settings(multicast_quake_enabled=True, multicast_search_size=3,
                       multicast_templates=templates, multicast_proxy_urls='')
        with patch.object(collector, '_run_with_key_rotation', new_callable=AsyncMock, return_value=[]) as search:
            await udpxy.collect_multicast(cfg, ['quake'], ['广东', '浙江'], session=Session(), log_fn=self.log)
            self.assertEqual(3, sum(call.args[3] for call in search.call_args_list))
            self.assertEqual(2, search.call_count)
            self.assertTrue(all('isp:"电信"' in call.args[2] for call in search.call_args_list))
            search.reset_mock()
            await udpxy.collect_multicast(cfg, ['fofa'], [], session=Session(), log_fn=self.log)
            search.assert_not_called()

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

    async def test_http_200_html_is_not_a_playable_proxy_and_stream_reads_are_bounded(self):
        for data, expected in ((b'<html>ok</html>' * 150, False), ((b'\x47' + bytes(187)) * 7, True)):
            response = Response({})
            response.content = MagicMock()
            response.content.readexactly = AsyncMock(return_value=data)
            session = Session(response)
            self.assertEqual(expected, await udpxy._stream_sample(session, 'http://8.8.8.8/rtp/239.1.1.1:80'))
            response.content.readexactly.assert_awaited_once_with(1316)
            self.assertFalse(session.calls[0][1]['allow_redirects'])

    async def test_timeout_keeps_verified_proxies_and_cancels_unfinished_probes(self):
        cfg = settings(multicast_proxy_urls='广东,电信,http://8.8.8.8\n广东,电信,http://1.1.1.1')
        cancelled = asyncio.Event()
        async def probe(proxy, *args):
            if '8.8.8.8' in proxy['url']:
                return {**proxy, 'active_clients': 0}
            try:
                await asyncio.sleep(10)
            finally:
                cancelled.set()
        with patch.object(udpxy, 'probe_proxy', side_effect=probe), patch.object(udpxy, 'MAX_RUN_SECONDS', 0.02):
            channels, _ = await udpxy.collect_multicast(cfg, [], [], session=Session(), log_fn=self.log)
        self.assertEqual(3, len(channels))
        self.assertTrue(cancelled.is_set())

    async def test_collector_allows_manual_only_run_without_search_keys(self):
        cfg = settings()
        manager = MagicMock()
        manager.get_key.return_value = None
        manager.get_all_keys.return_value = []
        async def probe(proxy, *args):
            return {**proxy, 'active_clients': 0}
        with patch('scanner_integration.key_manager.KeyManager.instance', return_value=manager), \
             patch.object(config, 'get_scan_config', return_value=cfg), \
             patch.object(collector, 'get_session', return_value=Session()), \
             patch.object(collector, '_is_stop_requested', return_value=False), \
             patch.object(udpxy, 'probe_proxy', side_effect=probe):
            channels, platforms, rows = await collector.collect_all(log_fn=self.log)
        self.assertEqual(3, len(channels))
        self.assertEqual(['udpxy'], platforms)
        self.assertEqual(3, rows[0]['cleaned_channels'])

    async def test_quake_endpoint_contract_and_partial_quota_results(self):
        items = [{'ip': '8.8.8.8', 'port': 4022, 'location': {'city_cn': '广州'}}] * 50
        session = Session(Response({'code': 0, 'data': items}), Response({'code': 400, 'message': '积分不足 secret'}))
        session.post = session.get
        async def read(response, limit):
            return json.dumps(response.data).encode()
        with patch.object(udpxy, 'read_response_limited', side_effect=read), \
             patch('asyncio.sleep', new_callable=AsyncMock), self.assertRaises(KeyDepletedError) as raised:
            await udpxy.search_quake_proxies('secret', 'udpxy', 60, session=session)
        self.assertEqual(50, len(raised.exception.partial_entries))
        self.assertNotIn('secret', str(raised.exception))
        self.assertEqual([0, 50], [call[1]['json']['start'] for call in session.calls])
        self.assertEqual([50, 10], [call[1]['json']['size'] for call in session.calls])
        self.assertFalse(session.calls[0][1]['allow_redirects'])

    async def test_multicast_failure_does_not_abort_other_collection_sources(self):
        cfg = settings(enabled_platforms=['quake'])
        manager = MagicMock()
        manager.get_key.side_effect = lambda platform: 'key' if platform == 'quake' else None
        manager.get_all_keys.side_effect = lambda platform: ['key'] if platform == 'quake' else []
        channel = {'name': 'CCTV1', 'url': 'http://8.8.8.8/live.m3u8', 'province': '广东'}
        with patch('scanner_integration.key_manager.KeyManager.instance', return_value=manager), \
             patch.object(config, 'get_scan_config', return_value=cfg), \
             patch.object(collector, 'get_session', return_value=Session()), \
             patch.object(collector, '_is_stop_requested', return_value=False), \
             patch.object(collector, 'collect_multicast', side_effect=RuntimeError('broken optional source')), \
             patch.object(collector, '_run_with_key_rotation', new_callable=AsyncMock, return_value=[channel]):
            channels, _, _ = await collector.collect_all(log_fn=self.log)
        self.assertEqual(1, len(channels))
        self.assertEqual('Quake 360', channels[0]['platform'])

    async def test_key_rotation_resumes_pagination_without_repeating_paid_rows(self):
        items = [{'ip': '8.8.8.8', 'port': 4022}] * 50
        session = Session(Response({'code': 0, 'data': items}),
                          Response({'code': 400, 'message': '积分不足'}),
                          Response({'code': 0, 'data': items[:10]}))
        session.post = session.get
        manager = MagicMock()
        manager.get_all_keys.return_value = ['first', 'second']
        manager.get_credits_info.return_value = {}
        stats = {}
        async def read(response, limit):
            return json.dumps(response.data).encode()
        with patch('scanner_integration.key_manager.KeyManager.instance', return_value=manager), \
             patch.object(udpxy, 'read_response_limited', side_effect=read), \
             patch('asyncio.sleep', new_callable=AsyncMock):
            proxies = await collector._run_with_key_rotation(
                'quake', udpxy.search_quake_proxies, 'udpxy', 60, session=session, stats=stats, cursor={})
        self.assertEqual(60, len(proxies))
        self.assertEqual(60, stats['api_items'])
        self.assertEqual([0, 50, 50], [call[1]['json']['start'] for call in session.calls])


class MulticastConfigAPITests(unittest.TestCase):
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

"""UDPXY collection/recheck expansion, using local fixtures only."""
import asyncio
import json
import unittest
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlsplit

from test_fofa_api import Session
from test_multicast import settings
from test_detection_expansion import seed
import database as db
from scanner_integration import config_bridge as config
from scanner_integration import detection_expansion as expansion
from scanner_integration.ip_scanner import IPScanner
from scanner_integration.platforms import collector, ip_extract, udpxy
from scanner_integration.safe_http import SafeResponse


PLAYBACK = 'http://8.8.8.8:4022/udpxy/rtp/239.1.1.1:1234'


async def playable(proxy, *args):
    return {**proxy, 'active_clients': None}


class SeedTests(unittest.TestCase):
    def test_playback_requires_public_http_ipv4_and_preserves_prefix(self):
        self.assertEqual(('http://8.8.8.8:4022/udpxy', ('rtp', '239.1.1.1:1234')),
                         udpxy.channel_proxy(PLAYBACK))
        for value in (None, 'invalid', PLAYBACK + '?token=x', PLAYBACK + '#x',
                      PLAYBACK.replace('http:', 'https:'), PLAYBACK.replace('8.8.8.8', '127.0.0.1'),
                      PLAYBACK.replace('8.8.8.8', 'user:pass@8.8.8.8'),
                      PLAYBACK.replace('8.8.8.8', '[2606:4700:4700::1111]'),
                      PLAYBACK.replace('239.1.1.1', '1.1.1.1'),
                      PLAYBACK.replace('/udpxy/', '/%2e%2e/')):
            with self.subTest(value=value):
                self.assertIsNone(udpxy.channel_proxy(value))

    def test_unique_template_and_ambiguous_or_unknown_destination_fallback(self):
        source = seed(PLAYBACK, ip_province='广东', operator='中国电信', city='广州')
        proxy, template = udpxy.seed_template(source, settings())
        self.assertEqual('custom', template['source'])
        self.assertEqual(3, len(template['channels']))
        self.assertEqual(('广东', '电信', '广州', 'Hunter'),
                         (proxy['province'], proxy['operator'], proxy['city'], proxy['platform']))
        templates = settings()['multicast_templates']
        templates.append({**templates[0], 'operator': '联通'})
        for source in (seed(PLAYBACK), seed(PLAYBACK, province='广东'),
                       seed(PLAYBACK.replace('239.1.1.1', '239.9.9.9'), province='广东')):
            with self.subTest(source=source):
                _, template = udpxy.seed_template(source, settings(multicast_templates=templates))
                self.assertEqual('verified', template['source'])
                self.assertEqual([{'name': 'CCTV1', 'protocol': 'rtp',
                                   'address': source['url'].rsplit('/', 1)[1]}], template['channels'])


class CollectionExpansionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(udpxy, '_is_stop_requested', return_value=False))
        self.stack.enter_context(patch.object(ip_extract, '_c_segment_cache',
                                             ip_extract._TTLCache(ttl=300, max_size=30)))

    async def test_collector_expands_verified_seeds_once_and_accounts_for_source(self):
        cfg = settings(enable_c_scan=True, c_scan_limit=2, multicast_max_proxies=10,
                       multicast_proxy_urls='', enabled_platforms=['fofa'], selected_provinces=['广东'])
        manager = MagicMock()
        manager.get_key.side_effect = lambda name: 'key' if name == 'fofa' else None
        manager.get_all_keys.side_effect = lambda name: ['key'] if name == 'fofa' else []

        async def search(*args, **kwargs):
            discovery = udpxy.current_discovery()
            for host in ('8.8.8.8', '8.8.8.9', '1.1.1.1'):
                await discovery.offer(f'http://{host}:4022/udpxy', '广东', '电信', '广州', direct=True)
            return []

        async def sample(session, url):
            return urlsplit(url).hostname != '1.1.1.1'

        self.stack.enter_context(patch('scanner_integration.key_manager.KeyManager.instance', return_value=manager))
        self.stack.enter_context(patch.object(config, 'get_scan_config', return_value=cfg))
        self.stack.enter_context(patch.object(collector, 'get_session', return_value=Session()))
        self.stack.enter_context(patch.object(collector, '_is_stop_requested', return_value=False))
        self.stack.enter_context(patch.object(collector, '_run_with_key_rotation', side_effect=search))
        status = SafeResponse(404, {}, b'', PLAYBACK, '8.8.8.8', 1)
        fetch = self.stack.enter_context(patch.object(udpxy, 'safe_fetch', new_callable=AsyncMock, return_value=status))
        self.stack.enter_context(patch.object(udpxy, '_stream_sample', side_effect=sample))
        channels, _, rows = await collector.collect_all(log_fn=MagicMock())
        self.assertEqual(5, fetch.call_count)  # Three seeds, two neighbors; no recursion.
        self.assertEqual({'8.8.8.6', '8.8.8.7', '8.8.8.8', '8.8.8.9'}, {ch['source_ip'] for ch in channels})
        self.assertEqual(12, len(channels))
        for channel in channels:
            self.assertEqual('Fofa', channel['platform'])
            self.assertEqual('广东', channel['ip_province'])
            self.assertEqual('电信', channel['operator'])
            self.assertIn(':4022/udpxy/', channel['url'])
            self.assertNotIn('bandwidth', channel)
            self.assertNotIn('stability', channel)
        row = next(row for row in rows if row['stat_key'] == channels[0]['yield_stat_key'])
        self.assertEqual((1, 2, 6, 12), (row['c_segment_segments'], row['c_segment_ips'],
                                       row['c_segment_channels'], row['cleaned_channels']))
        self.assertIsNone(udpxy.current_discovery())

    async def test_udpxy_shares_ordinary_scan_source_global_budget_and_cache(self):
        cfg = settings(enable_c_scan=True, c_scan_limit=2, c_segment_max_total_ips=4,
                       c_segment_per_source_max_ips=3, c_segment_per_source_max_segments=3)
        self.stack.enter_context(patch.object(config, 'get_scan_config', return_value=cfg))
        token = ip_extract.begin_c_segment_budget(cfg)
        try:
            with udpxy.discovery_source('Fofa', 'fofa-main'), \
                 patch.object(ip_extract, 'extract_channels_from_ip', new_callable=AsyncMock, return_value=[]):
                await ip_extract.smart_c_segment_scan([('9.9.9.9', 4022)], Session())
            discovery = udpxy.MulticastDiscovery(cfg, ['广东'])
            for host, key in (('8.8.8.8', 'fofa-main'), ('1.1.1.1', 'hunter-main'), ('4.2.2.2', 'quake-main')):
                discovery.add(f'http://{host}:4022', source={'stat_key': key})
            with patch.object(udpxy, 'probe_proxy', side_effect=playable) as probe:
                await discovery.finish(Session(), expand_c_segments=True)
            self.assertEqual(5, probe.call_count)
            self.assertEqual(4, ip_extract.get_c_segment_budget().ips_used)
            self.assertEqual(1, discovery.expansion_stats['fofa-main']['c_segment_ips'])
            self.assertEqual(1, discovery.expansion_stats['hunter-main']['c_segment_ips'])
            self.assertEqual(1, discovery.expansion_stats['quake-main']['c_segment_budget_skipped'])
        finally:
            ip_extract.end_c_segment_budget(token)
        repeated = udpxy.MulticastDiscovery(cfg, ['广东'])
        repeated.add('http://8.8.8.8:4022', source={'stat_key': 'another-source'})
        with patch.object(udpxy, 'probe_proxy', side_effect=playable) as probe:
            await repeated.finish(Session(), expand_c_segments=True)
        self.assertEqual(1, probe.call_count)
        self.assertEqual(1, repeated.expansion_stats['another-source']['c_segment_cache_skipped'])

    async def test_proxy_channel_caps_and_disabled_expansion(self):
        for enabled, expected_probes in ((True, 3), (False, 1)):
            with self.subTest(enabled=enabled):
                cfg = settings(enable_c_scan=enabled, c_scan_limit=20,
                               multicast_max_proxies=3, multicast_max_channels=2)
                discovery = udpxy.MulticastDiscovery(cfg, ['广东'])
                discovery.add('http://8.8.8.8:4022')
                with patch.object(udpxy, 'probe_proxy', side_effect=playable) as probe:
                    channels = await discovery.finish(Session(), expand_c_segments=True)
                self.assertEqual(expected_probes, probe.call_count)
                self.assertEqual(2, len(channels))

    async def test_explicit_ip_scan_keeps_target_scope_even_when_c_scan_enabled(self):
        scanner = IPScanner({'scan_config': settings(enable_c_scan=True),
                             'multicast_province': '广东', 'multicast_operator': '电信'})
        with patch.object(udpxy, 'probe_proxy', side_effect=playable) as probe, \
             patch('scanner_integration.network.get_session', return_value=Session()), \
             patch('scanner_integration.ip_scanner.safe_fetch', new_callable=AsyncMock):
            results = await scanner.scan_targets('8.8.8.8:4022', ['MULTICAST'], [80])
        self.assertEqual(1, probe.call_count)
        self.assertEqual(3, results[0]['channel_count'])
        self.assertEqual('http://8.8.8.8:4022', probe.call_args.args[0]['url'])

    async def test_timeout_cancels_neighbors_retains_seed_and_cache(self):
        cfg = settings(enable_c_scan=True, c_scan_limit=2)
        discovery = udpxy.MulticastDiscovery(cfg, ['广东'])
        discovery.add('http://8.8.8.8:4022')
        cancelled = []

        async def probe(proxy, *args):
            if not proxy.get('c_segment_expanded'):
                return await playable(proxy)
            try:
                await asyncio.Future()
            finally:
                cancelled.append(proxy['url'])

        with patch.object(udpxy, 'probe_proxy', side_effect=probe), patch.object(udpxy, 'MAX_RUN_SECONDS', 0.03):
            channels = await discovery.finish(Session(), expand_c_segments=True)
        self.assertEqual(2, len(cancelled))
        self.assertEqual(3, len(channels))
        self.assertIsNotNone(ip_extract._c_segment_cache.get(('8.8.8', 4022)))


class RecheckExpansionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cfg = settings(enable_c_scan=True, detection_expansion_enabled=True,
                            detection_expansion_max_ips=5, detection_expansion_max_channels=10,
                            multicast_max_proxies=2, multicast_max_channels=3)
        self.source = seed(PLAYBACK, ip_province='广东', operator='电信', city='广州')
        self.store = {}
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(db, 'acquire_task_lease', return_value=(True, {})))
        self.finish = self.stack.enter_context(patch.object(db, 'finish_task_lease'))
        self.stack.enter_context(patch.object(db, 'get_config_data', side_effect=self.store.get))
        self.stack.enter_context(patch.object(db, 'set_config_data', side_effect=lambda key, value: self.store.update({key: value})))
        self.stack.enter_context(patch.object(db, 'get_all_persistent_for_check', return_value=[]))
        self.upsert = self.stack.enter_context(patch.object(db, 'upsert_persistent_results'))
        self.update = self.stack.enter_context(patch.object(db, 'batch_update_persistent_checks'))
        self.stack.enter_context(patch.object(expansion, 'get_session', return_value=Session()))
        self.deep = self.stack.enter_context(patch.object(expansion, 'deep_filter_batch', side_effect=self.quality_check))
        self.log = MagicMock()

    async def quality_check(self, channels, *args):
        return [{**channel, 'stability': 90, 'delay': 100, 'bandwidth': 2 if i == 0 else 0,
                 'resolution': '1920x1080'} for i, channel in enumerate(channels)]

    async def test_recheck_probes_original_prefix_and_budgets_then_deep_checks_before_saving(self):
        # Exercise real probe_neighbor/probe_proxy; only replace network responses.
        status = SafeResponse(404, {}, b'', PLAYBACK, '8.8.8.8', 1)
        with patch.object(udpxy, 'safe_fetch', new_callable=AsyncMock, return_value=status), \
             patch.object(udpxy, '_stream_sample', new_callable=AsyncMock, return_value=True) as sample, \
             patch.object(expansion, 'extract_channels_from_ip', new_callable=AsyncMock) as ordinary:
            result = await expansion.expand_after_detection([self.source], self.cfg, self.log)
            self.assertEqual({'probed_ips': 2, 'segments': 1, 'discovered': 3, 'added': 1}, result)
            self.assertEqual(2, sample.call_count)
            ordinary.assert_not_called()
            for call in sample.call_args_list:
                self.assertIn(urlsplit(call.args[1]).hostname, ('8.8.8.7', '8.8.8.9'))
                self.assertIn(':4022/udpxy/rtp/', call.args[1])
            candidates = self.deep.call_args.args[0]
            self.assertEqual(3, len(candidates))
            self.assertTrue(all('stability' not in ch and 'bandwidth' not in ch for ch in candidates))
            accepted = self.upsert.call_args.args[0]
            self.assertEqual(1, len(accepted))
            self.assertEqual('Hunter', accepted[0]['platform'])
            self.assertEqual('广东', accepted[0]['ip_province'])
            self.assertEqual('电信', accepted[0]['operator'])
            self.assertNotEqual('8.8.8.8', accepted[0]['source_ip'])
            self.assertTrue(accepted[0]['c_segment_expanded'])
            self.assertTrue(self.update.call_args.args[0][0]['ok'])
            sample.reset_mock()
            await expansion.expand_after_detection([self.source], self.cfg, self.log)
            sample.assert_not_called()
        self.assertEqual(1, len(json.loads(self.store[expansion.COOLDOWN_KEY])))
        self.assertEqual('completed', self.finish.call_args.kwargs['state'])

    async def test_missing_template_uses_verified_channel_and_failed_proxies_add_nothing(self):
        for passes in (True, False):
            with self.subTest(passes=passes):
                self.store.clear()
                self.deep.reset_mock()
                self.upsert.reset_mock()
                source = seed(PLAYBACK.replace('239.1.1.1', '239.9.9.9'))
                with patch.object(udpxy, 'probe_proxy', side_effect=playable if passes else None,
                                  return_value=None) as probe:
                    result = await expansion.expand_after_detection([source], self.cfg, self.log)
                self.assertEqual('verified', probe.call_args.args[1]['source'])
                self.assertEqual(1, len(probe.call_args.args[1]['channels']))
                if passes:
                    self.assertEqual(2, result['discovered'])
                    self.assertTrue(all(ch['url'].endswith('/rtp/239.9.9.9:1234')
                                        for ch in self.deep.call_args.args[0]))
                else:
                    self.assertEqual(0, result['discovered'])
                    self.upsert.assert_not_called()

    async def test_duplicate_existing_or_off_endpoint_candidates_never_reach_deep_check(self):
        existing = 'http://8.8.8.7:4022/udpxy/rtp/239.1.1.1:1234'
        self.stack.enter_context(patch.object(db, 'get_all_persistent_for_check', return_value=[{'url': existing}]))

        async def probe(proxy, template, ip, port, *args):
            channel = {'name': 'CCTV2', 'url': f'http://{ip}:{port}/udpxy/udp/239.1.1.2:1234'}
            return [channel, channel, {'name': 'CCTV1', 'url': existing},
                    {'name': 'CCTV1', 'url': 'http://1.1.1.1:4022/udpxy/rtp/239.1.1.1:1234'}]

        with patch.object(expansion, 'probe_neighbor', side_effect=probe):
            result = await expansion.expand_after_detection([self.source], self.cfg, self.log)
        candidates = self.deep.call_args.args[0]
        self.assertEqual(2, result['discovered'])
        self.assertEqual(2, len({ch['url'] for ch in candidates}))
        self.assertTrue(all(ch['url'].endswith('/udp/239.1.1.2:1234') for ch in candidates))

    def test_disabled_multicast_skips_udpxy_seeds_but_keeps_regular_sources(self):
        cfg = {**self.cfg, 'multicast_enabled': False}
        regular = seed('http://1.1.1.1:8080/live')
        plans = expansion.plan_expansion([self.source, regular], cfg, {}, 100000)
        self.assertEqual([regular], [source for _, source, _ in plans])
        failed = {**self.source, 'bandwidth': 0}
        self.assertEqual([], expansion.plan_expansion([failed], self.cfg, {}, 100000))

    async def test_cancelled_neighbor_probes_release_lease_and_preserve_cooldown(self):
        started = asyncio.Event()
        cancelled = []

        async def probe(proxy, *args):
            started.set()
            try:
                await asyncio.Future()
            finally:
                cancelled.append(proxy['url'])

        with patch.object(udpxy, 'probe_proxy', side_effect=probe):
            task = asyncio.create_task(expansion.expand_after_detection([self.source], self.cfg, self.log))
            await asyncio.wait_for(started.wait(), timeout=2)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(2, len(cancelled))
        self.assertTrue(json.loads(self.store[expansion.COOLDOWN_KEY]))
        self.assertEqual('cancelled', self.finish.call_args.kwargs['state'])
        self.upsert.assert_not_called()

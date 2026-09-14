import asyncio
import json
import unittest
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

from test_fofa_api import Response, Session
import database as db
from scanner_integration import config_bridge as config
from scanner_integration import detection_expansion as expansion
from scanner_integration.detection import DetectionManager


def seed(url='http://8.8.8.8:8080/live', **kwargs):
    return dict(url=url, name='CCTV1', stability=90, bandwidth=2, delay=100,
                platform='Hunter', **kwargs)


class ExpansionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cfg = config._normalize_scan_config({'detection_expansion_max_ips': 2,
                                                  'detection_expansion_max_channels': 2})
        self.log = MagicMock()

    def test_only_fresh_quality_public_http_sources_and_budgeted_neighbors(self):
        sources = [seed(), seed('http://1.1.1.1:8080/live'),
                   seed('http://192.168.3.61:8080/live'), seed('https://8.8.4.4/live'),
                   seed('http://example.com/live'), {**seed('http://9.9.9.9/live'), 'bandwidth': 0}]
        plans = expansion.plan_expansion(sources, self.cfg, {}, 100000)
        self.assertEqual(2, len(plans))
        self.assertEqual(2, sum(len(ips) for _, _, ips in plans))
        endpoints = {expansion.public_http_endpoint(s['url']) for s in sources}
        self.assertFalse(endpoints & {ip for _, _, ips in plans for ip in ips})
        cooled = {key: 100000 for key, _, _ in plans}
        self.assertEqual([], expansion.plan_expansion(sources, self.cfg, cooled, 100001))

    async def test_disabled_does_no_work(self):
        with patch.object(db, 'acquire_task_lease') as acquire:
            for field in ('enable_c_scan', 'detection_expansion_enabled'):
                await expansion.expand_after_detection([seed()], {**self.cfg, field: False}, self.log)
            acquire.assert_not_called()

    def test_detection_database_reads_include_source_metadata(self):
        from database import db as storage
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = []
        with patch.object(storage, '_get_conn', return_value=conn), \
             patch.object(config, 'get_scan_config', return_value=self.cfg):
            storage.get_all_persistent_for_check()
            storage.get_persistent_for_check_tiered()
        for call in conn.execute.call_args_list:
            selected = call.args[0].split('FROM')[0]
            for field in ('platform', 'province', 'city', 'source_ip'):
                self.assertIn(field, selected)

    async def test_same_port_extraction_never_probes_fallback_ports(self):
        session = Session(*(Response({}, 404) for _ in range(20)))
        with patch('scanner_integration.platforms.ip_extract._get_extract_cache', return_value=None), \
             patch('scanner_integration.platforms.ip_extract._set_extract_cache'):
            await expansion.extract_channels_from_ip('8.8.8.8', 1234, session, include_fallback_ports=False)
        self.assertTrue(session.calls)
        self.assertTrue(all(url.startswith('http://8.8.8.8:1234/') for url, _ in session.calls))

    async def test_busy_lease_prevents_duplicate_expansion(self):
        with patch.object(db, 'acquire_task_lease', return_value=(False, {})), \
             patch.object(db, 'get_config_data') as read:
            result = await expansion.expand_after_detection([seed()], self.cfg, self.log)
            self.assertEqual(0, result['probed_ips'])
            read.assert_not_called()

    async def test_timeout_and_cancellation_release_lease_and_keep_cooldown(self):
        for error in (asyncio.TimeoutError, asyncio.CancelledError):
            with self.subTest(error=error), ExitStack() as stack:
                stack.enter_context(patch.object(db, 'acquire_task_lease', return_value=(True, {})))
                finish = stack.enter_context(patch.object(db, 'finish_task_lease'))
                stack.enter_context(patch.object(db, 'get_config_data', return_value='{}'))
                saved = stack.enter_context(patch.object(db, 'set_config_data'))
                stack.enter_context(patch.object(db, 'get_all_persistent_for_check', return_value=[]))
                upsert = stack.enter_context(patch.object(db, 'upsert_persistent_results'))
                stack.enter_context(patch.object(expansion, 'get_session', return_value=Session()))
                async def extract(ip, port, *args, **kwargs):
                    return [{'name': 'CCTV1', 'url': f'http://{ip}:{port}/new'}]
                stack.enter_context(patch.object(expansion, 'extract_channels_from_ip', side_effect=extract))
                stack.enter_context(patch.object(expansion, 'deep_filter_batch', side_effect=error))
                if error is asyncio.CancelledError:
                    with self.assertRaises(asyncio.CancelledError):
                        await expansion.expand_after_detection([seed()], self.cfg, self.log)
                    self.assertEqual('cancelled', finish.call_args.kwargs['state'])
                else:
                    result = await expansion.expand_after_detection([seed()], self.cfg, self.log)
                    self.assertTrue(result['timed_out'])
                saved.assert_called_once()
                upsert.assert_not_called()

    async def test_new_channels_are_deduplicated_deep_checked_and_cooldown_survives_run(self):
        store = {}
        async def extract(ip, port, *args, **kwargs):
            channel = {'url': f'http://{ip}:{port}/new', 'name': 'CCTV1'}
            return [channel, channel, {'url': 'http://127.0.0.1/admin', 'name': 'CCTV1'}]
        async def deep(channels, *args):
            return [{**ch, 'stability': 80, 'bandwidth': 2 if i == 0 else 0,
                     'delay': 100, 'resolution': '1920x1080'} for i, ch in enumerate(channels)]
        with ExitStack() as stack:
            stack.enter_context(patch.object(db, 'acquire_task_lease', return_value=(True, {})))
            finish = stack.enter_context(patch.object(db, 'finish_task_lease'))
            stack.enter_context(patch.object(db, 'get_config_data', side_effect=lambda key: store.get(key)))
            stack.enter_context(patch.object(db, 'set_config_data', side_effect=lambda key, value: store.update({key: value})))
            stack.enter_context(patch.object(db, 'get_all_persistent_for_check', return_value=[]))
            upsert = stack.enter_context(patch.object(db, 'upsert_persistent_results'))
            update = stack.enter_context(patch.object(db, 'batch_update_persistent_checks'))
            stack.enter_context(patch.object(expansion, 'get_session', return_value=Session()))
            probe = stack.enter_context(patch.object(expansion, 'extract_channels_from_ip', side_effect=extract))
            stack.enter_context(patch.object(expansion, 'deep_filter_batch', side_effect=deep))
            result = await expansion.expand_after_detection([seed()], self.cfg, self.log)
            self.assertEqual({'probed_ips': 2, 'segments': 1, 'discovered': 2, 'added': 1}, result)
            accepted = upsert.call_args.args[0]
            self.assertEqual('Hunter', accepted[0]['platform'])
            self.assertTrue(update.call_args.args[0][0]['ok'])
            self.assertEqual(1, len(json.loads(store[expansion.COOLDOWN_KEY])))
            probe.reset_mock()
            await expansion.expand_after_detection([seed()], self.cfg, self.log)
            probe.assert_not_called()
            self.assertEqual('completed', finish.call_args.kwargs['state'])

    async def test_detection_hook_uses_only_successful_candidates(self):
        manager = DetectionManager()
        rows = [seed(), seed('http://1.1.1.1/live')]
        with ExitStack() as stack:
            stack.enter_context(patch.object(db, 'get_persistent_for_check_tiered', return_value=rows))
            stack.enter_context(patch.object(db, 'get_consecutive_failures_batch', return_value={}))
            stack.enter_context(patch.object(db, 'delete_persistent_by_threshold', return_value=0))
            for name in ('insert_detection_run', 'insert_detection_results', 'finish_detection_run',
                         'batch_update_persistent_checks', 'cleanup_old_detection_runs',
                         'cleanup_quality_history', 'cleanup_old_run_logs', 'flush_log_buffer', 'clear_detection_logs'):
                stack.enter_context(patch.object(db, name))
            stack.enter_context(patch.object(manager, '_log'))
            stack.enter_context(patch('scanner_integration.detection.get_session', return_value=Session()))
            stack.enter_context(patch('scanner_integration.detection.run_deep_check', side_effect=[seed(), None, None]))
            stack.enter_context(patch('scanner_integration.detection._evaluate_quality_safe', return_value='good'))
            stack.enter_context(patch('asyncio.sleep', new_callable=AsyncMock))
            expand = stack.enter_context(patch.object(expansion, 'expand_after_detection', new_callable=AsyncMock,
                                                     return_value={'added': 1}))
            await manager._run_detection_cycle_inner(self.cfg, 'manual')
            self.assertEqual([rows[0]['url']], [s['url'] for s in expand.call_args.args[0]])
            self.assertEqual({'added': 1}, manager.status['last_cycle_result']['expansion'])

import asyncio
import base64
import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from flask import Flask

import database

with patch.object(database, '_get_conn', side_effect=RuntimeError('offline test import')):
    import scanner_integration
from scanner_integration.fofa_api import FofaAPIError, request_fofa, with_fofa_filters
from scanner_integration.key_manager import KeyManager, check_all_fofa_credits, check_fofa_credit
from scanner_integration.platforms.fofa import fofa_scan
from scanner_integration.platforms.collector import _run_with_key_rotation, collect_all
from scanner_integration.platforms.ip_extract import extract_channels_from_ip
from scanner_integration.platforms.shared import KeyDepletedError
from scanner_integration.secure_keys import key_id


def load_scan_routes():
    """Import the real routes without executing the WSGI startup module."""
    previous = {name: module for name, module in sys.modules.items()
                if name == 'web' or name.startswith('web.')}
    for name in previous:
        sys.modules.pop(name)
    package = types.ModuleType('web')
    package.__path__ = [str(Path(__file__).resolve().parents[1] / 'web')]
    sys.modules['web'] = package
    try:
        return importlib.import_module('web.routes.scan')
    finally:
        for name in list(sys.modules):
            if name == 'web' or name.startswith('web.'):
                sys.modules.pop(name)
        sys.modules.update(previous)


scan_routes = load_scan_routes()


class Response:
    def __init__(self, data, status=200):
        self.data, self.status = data, status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def json(self, **kwargs):
        if isinstance(self.data, Exception):
            raise self.data
        return self.data


class Session(Response):
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []
        self.closed = False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response

    async def close(self):
        self.closed = True

    async def __aexit__(self, *args):
        await self.close()


class FofaTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.km = KeyManager()
        self.manager = patch.object(KeyManager, 'instance', return_value=self.km)
        self.manager.start()
        self.addCleanup(self.manager.stop)
        self.sleep = patch('asyncio.sleep', new_callable=AsyncMock)
        self.sleep.start()
        self.addCleanup(self.sleep.stop)
        self.config = patch('scanner_integration.config_bridge.get_scan_config', return_value={})
        self.config.start()
        self.addCleanup(self.config.stop)

    async def test_account_uses_key_only_and_preserves_units_zero_and_unknown(self):
        session = Session(Response({
            'error': False, 'fcoin': 0, 'fofa_point': '49200',
            'remain_api_query': 49992, 'remain_api_data': 499398, 'vip_level': 12,
        }))
        info = await check_fofa_credit(' test-key ', session)
        self.assertTrue(info['ok'])
        self.assertEqual(49200, info['credit'])
        self.assertEqual(0, info['balances']['fcoin'])
        self.assertIsNone(info['balances']['remain_free_point'])
        self.assertEqual(499398, info['balances']['remain_api_data'])
        url, args = session.calls[0]
        self.assertEqual('https://fofa.info/api/v1/info/my', url)
        self.assertEqual({'key': 'test-key'}, args['params'])
        self.assertFalse(args['allow_redirects'])
        self.assertFalse(session.closed)

    async def test_account_closes_owned_session_on_error(self):
        session = Session(Response({'error': True, 'errmsg': 'invalid key secret'}))
        with patch('scanner_integration.network.get_session', return_value=session):
            info = await check_fofa_credit('secret')
        self.assertNotIn('secret', info['error'])
        self.assertTrue(session.closed)

    async def test_zero_points_does_not_disable_monthly_quota_or_free_points(self):
        self.km.load_keys('fofa', ['key'])
        self.km.mark_depleted('fofa', 'key')
        session = Session(Response({'error': False, 'fofa_point': 0, 'remain_api_data': 1000}))
        with patch('scanner_integration.network.get_session', return_value=session):
            result = await check_all_fofa_credits()
        self.assertEqual(0, result[0]['credit'])
        self.assertIsNone(self.km.get_credits_info('fofa')['key'])
        scan = AsyncMock(return_value=['channel'])
        self.assertEqual(['channel'], await _run_with_key_rotation('fofa', scan))
        scan.assert_awaited_once()

    async def test_transient_errors_retry_but_permissions_are_not_depletion(self):
        session = Session(Response({}, 429), Response({}, 503), Response({'error': False}))
        await request_fofa(session, 'info/my', 'key')
        self.assertEqual(3, len(session.calls))
        for status in (200, 403):
            with self.subTest(status=status):
                session = Session(Response({'error': True, 'errmsg': '没有权限'}, status))
                with self.assertRaises(FofaAPIError) as error:
                    await request_fofa(session, 'search/all', 'key')
                self.assertFalse(error.exception.depleted)
                self.assertEqual(1, len(session.calls))

    async def test_malformed_and_network_responses_do_not_leak_credentials(self):
        for payload in ([], ValueError('bad JSON')):
            info = await check_fofa_credit('secret', Session(Response(payload)))
            self.assertIn('error', info)
        session = Session(*(asyncio.TimeoutError('url?key=secret') for _ in range(3)))
        info = await check_fofa_credit('secret', session)
        self.assertIn('超时', info['error'])
        self.assertNotIn('secret', info['error'])

    async def test_search_encoding_size_and_field_order_without_email(self):
        query = 'title="电视直播?"'
        rows = [['8.8.8.8', '8080', '浙江', '杭州'], ['bad-ip', 80, '', ''], ['1.1.1.1', 0, '', '']]
        session = Session(Response({'error': False, 'results': rows, 'size': 3}))
        with patch('scanner_integration.platforms.fofa.extract_channels_from_ip', new_callable=AsyncMock, return_value=['channel']) as extract:
            result = await fofa_scan('key', query, 75, session)
        self.assertEqual(['channel'], result)
        extract.assert_awaited_once_with('8.8.8.8', 8080, session, '浙江', '杭州')
        params = session.calls[0][1]['params']
        self.assertEqual(base64.b64encode(query.encode()).decode(), params['qbase64'])
        self.assertEqual(query, base64.b64decode(params['qbase64'], validate=True).decode())
        self.assertNotIn('email', params)
        self.assertEqual(75, params['size'])
        self.assertEqual('ip,port,region,city', params['fields'])

    async def test_pagination_keeps_size_constant_and_bounds_extraction(self):
        row = ['8.8.8.8', 80, '', '']
        session = Session(Response({'error': False, 'results': [row] * 10000}),
                          Response({'error': False, 'results': [row] * 5}))
        with patch('scanner_integration.platforms.fofa.extract_channels_from_ip', new_callable=AsyncMock, return_value=[]) as extract:
            await fofa_scan('key', 'query', 10001, session)
        self.assertEqual([10000, 10000], [args['params']['size'] for _, args in session.calls])
        self.assertEqual([1, 2], [args['params']['page'] for _, args in session.calls])
        self.assertEqual(10001, extract.await_count)

    async def test_search_depletion_rotates_and_preserves_partial_results(self):
        self.km.load_keys('fofa', ['first', 'second'])
        error = KeyDepletedError('F点不足')
        error.partial_entries = ['existing-channel']
        scan = AsyncMock(side_effect=[error, ['new-channel']])
        self.assertEqual(['existing-channel', 'new-channel'], await _run_with_key_rotation('fofa', scan))
        self.assertEqual(0, self.km.get_credits_info('fofa')['first'])
        session = Session(Response({'error': True, 'errmsg': 'F点余额不足'}))
        with self.assertRaises(KeyDepletedError):
            await fofa_scan('key', 'query', 1, session)

    async def test_owned_search_session_is_closed(self):
        session = Session(Response({'error': False, 'results': []}))
        with patch('scanner_integration.platforms.fofa.get_session', return_value=session):
            self.assertEqual([], await fofa_scan('key', 'query', 1))
        self.assertTrue(session.closed)

    async def test_parallel_requests_are_paced_per_key(self):
        session = Session(Response({'error': False}), Response({'error': False}))
        with patch('scanner_integration.fofa_api.time.monotonic', return_value=100), \
             patch('asyncio.sleep', new_callable=AsyncMock) as sleep:
            await asyncio.gather(request_fofa(session, 'info/my', 'key'),
                                 request_fofa(session, 'info/my', 'key'))
        sleep.assert_awaited_once()
        self.assertAlmostEqual(0.6, sleep.await_args.args[0])

    async def test_automatic_platform_selection_accepts_fofa_without_email(self):
        self.km.load_keys('fofa', ['key'])
        cfg = {'cost_saver_mode': True, 'quality_discovery_enabled': False,
               'selected_provinces': ['浙江'], 'operator': '电信'}
        with patch('scanner_integration.config_bridge.get_scan_config', return_value=cfg), \
             patch('scanner_integration.platforms.collector.get_session', return_value=Session()), \
             patch('scanner_integration.platforms.collector.fofa_scan', new_callable=AsyncMock, return_value=[]) as scan, \
             patch('scanner_integration.domain_ip_scanner.domain_ip_scan', new_callable=AsyncMock, return_value=[]):
            _, platforms, _ = await collect_all(size=1)
        self.assertEqual(['fofa'], platforms)
        self.assertIn('org="CHINANET"', scan.await_args.args[1])
        self.assertIn('region="浙江"', scan.await_args.args[1])

    async def test_ipv6_host_extraction_brackets_url_without_changing_source_ip(self):
        session = Session(*(Response({}, 404) for _ in range(20)))
        with patch('scanner_integration.platforms.ip_extract._get_extract_cache', return_value=None), \
             patch('scanner_integration.platforms.ip_extract._set_extract_cache'):
            await extract_channels_from_ip('2606:4700:4700::1111', 8080, session)
        self.assertEqual('http://[2606:4700:4700::1111]:8080/iptv/live/zh_cn.js', session.calls[0][0])

    def test_filters_use_org_aliases_and_escape_values(self):
        query = with_fofa_filters('body="IPTV" || title="直播"', '浙江', '电信')
        self.assertIn('(body="IPTV" || title="直播") && region="浙江"', query)
        self.assertIn('org="CHINANET"', query)
        self.assertNotIn('isp=', query)
        self.assertIn('org="a\\"b"', with_fofa_filters('query', operator='a"b'))


class FofaKeyRouteTests(unittest.TestCase):
    def test_credits_route_returns_verified_units_without_key(self):
        app = Flask(__name__)
        app.register_blueprint(scan_routes.scan_bp)
        km = KeyManager()
        km.load_keys('fofa', ['secret-key'])
        bridge = types.SimpleNamespace(run_sync=lambda coro, timeout: asyncio.run(coro))
        with patch.object(scan_routes, '_ensure_scan_bridge', return_value=(types.SimpleNamespace(bridge=bridge), None, 200)), \
             patch('scanner_integration.key_manager.init_key_manager'), \
             patch.object(KeyManager, 'instance', return_value=km), \
             patch('scanner_integration.config_bridge.get_scan_config', return_value={}), \
             patch('scanner_integration.key_manager.check_all_quake_credits', new_callable=AsyncMock, return_value=[]), \
             patch('scanner_integration.key_manager.check_all_hunter_credits', new_callable=AsyncMock, return_value=[]), \
             patch('scanner_integration.key_manager.check_all_daydaymap_credits', new_callable=AsyncMock, return_value=[]), \
             patch('scanner_integration.key_manager.check_all_fofa_credits', new_callable=AsyncMock, return_value=[{
                 'credit': 0, 'verified': True, 'balances': {'fcoin': 0, 'remain_api_data': 100},
             }]):
            response = app.test_client().get('/api/scan/keys/credits')
        self.assertEqual(200, response.status_code)
        row = response.json['data'][0]
        self.assertTrue(row['verified'])
        self.assertEqual({'fcoin': 0, 'remain_api_data': 100}, row['balances'])
        self.assertNotIn('secret-key', response.get_data(as_text=True))

    def test_add_and_update_without_email(self):
        app = Flask(__name__)
        app.register_blueprint(scan_routes.scan_bp)
        config = {'fofa_api_keys': []}
        with patch('scanner_integration.config_bridge.get_scan_config', return_value=config), \
             patch('scanner_integration.config_bridge.save_scan_config') as save, \
             patch('scanner_integration.key_manager.init_key_manager'):
            client = app.test_client()
            response = client.post('/api/scan/keys', json={'platform': 'fofa', 'key': 'first'})
            self.assertEqual(200, response.status_code)
            response = client.put('/api/scan/keys', json={
                'platform': 'fofa', 'key_id': key_id('fofa', 'first'), 'new_key': 'second',
            })
            self.assertEqual(200, response.status_code)
            self.assertEqual(['second'], save.call_args.args[0]['fofa_api_keys'])

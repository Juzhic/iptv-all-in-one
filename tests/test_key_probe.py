import asyncio
import base64
import json
import types
import unittest
from unittest.mock import AsyncMock, patch

from flask import Flask
from test_fofa_api import Response, Session, scan_routes
from scanner_integration.key_probe import probe_key
from scanner_integration.secure_keys import key_id


class ProbeSession(Session):
    post = Session.get


class KeyProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_fofa_points_failure_keeps_free_and_monthly_balances_visible(self):
        session = ProbeSession(Response({'error': False, 'fofa_point': 0, 'remain_free_point': 20,
                                         'remain_api_query': 30, 'remain_api_data': 100,
                                         'email': 'private@example.com'}),
                               Response({'error': True, 'errmsg': '[820031] F点余额不足'}))
        result = await probe_key('fofa', 'secret', {}, session)
        account, search = result['steps']
        self.assertEqual(100, account['balances']['remain_api_data'])
        self.assertIn('免费 F 点：20', account['message'])
        self.assertEqual('820031', search['code'])
        self.assertIn('不代表免费/月度 API 额度全部耗尽', search['message'])
        self.assertEqual('quota_exhausted', search['state'])
        self.assertNotIn('private@example.com', json.dumps(result))
        self.assertEqual(2, len(session.calls))

    def setUp(self):
        sleep = patch('asyncio.sleep', new_callable=AsyncMock)
        sleep.start()
        self.addCleanup(sleep.stop)

    async def test_hunter_account_failure_does_not_hide_successful_zero_result_search(self):
        session = ProbeSession(Response({'code': 400, 'message': '账号接口不可用'}),
                               Response({'code': 200, 'data': {'arr': []}}))
        result = await probe_key('hunter', 'stored-key', {'search_keywords': ['title:电视']}, session)
        self.assertTrue(result['usable'])
        self.assertEqual(['api_error', 'passed'], [s['state'] for s in result['steps']])
        self.assertIn('零匹配', result['steps'][1]['message'])
        self.assertEqual(2, len(session.calls))
        self.assertTrue(session.calls[0][0].endswith('/openApi/userInfo'))
        self.assertTrue(session.calls[1][0].endswith('/openApi/search'))
        params = session.calls[1][1]['params']
        self.assertEqual(1, params['page_size'])
        self.assertEqual('web.title="电视"', base64.urlsafe_b64decode(params['search']).decode())
        self.assertNotIn('stored-key', json.dumps(result))
        self.assertFalse(session.calls[0][1]['allow_redirects'])

    async def test_account_success_does_not_imply_search_permission(self):
        session = ProbeSession(Response({'code': 200, 'data': {}}),
                               Response({'code': 403, 'message': '账号无 API 访问权限，需升级为付费账号'}, 403))
        result = await probe_key('hunter', 'key', {}, session)
        self.assertFalse(result['usable'])
        self.assertEqual('permission_denied', result['state'])
        self.assertEqual('passed', result['steps'][0]['state'])

    async def test_classifies_failures_and_never_retries(self):
        cases = [(401, 'invalid api key secret', 'auth_failed'),
                 (400, '积分不足', 'quota_exhausted'),
                 (429, 'too many requests', 'rate_limited'),
                 (503, 'service down', 'unavailable'),
                 (400, '语法错误', 'api_error')]
        for status, message, expected in cases:
            session = ProbeSession(Response({'error': False}),
                                   Response({'error': True, 'errmsg': message}, status))
            result = await probe_key('fofa', 'secret', {}, session)
            self.assertEqual(expected, result['state'])
            self.assertEqual(2, len(session.calls))
            self.assertNotIn('secret', json.dumps(result))

    async def test_timeout_or_malformed_response_cannot_declare_key_expired(self):
        for response in (asyncio.TimeoutError('url?key=secret'), Response(ValueError('html')),
                         Response({'code': 200, 'data': {}})):
            result = await probe_key('daydaymap', 'secret', {}, ProbeSession(response))
            self.assertIsNone(result['usable'])
            self.assertEqual('unknown', result['state'])
            self.assertNotIn('secret', json.dumps(result))

    async def test_all_platforms_request_one_search_item_and_no_target_visits(self):
        cases = {
            'fofa': [Response({'error': False}), Response({'error': False, 'results': [['192.0.2.1', 80]]})],
            'quake': [Response({'code': 0, 'data': {}}), Response({'code': 0, 'data': []})],
            'daydaymap': [Response({'code': 200, 'data': {'list': []}})],
        }
        for platform, responses in cases.items():
            session = ProbeSession(*responses)
            result = await probe_key(platform, 'secret', {}, session)
            self.assertTrue(result['usable'])
            self.assertEqual(len(responses), len(session.calls))
            body = session.calls[-1][1].get('json', session.calls[-1][1].get('params'))
            self.assertEqual(1, body.get('size', body.get('page_size')))
            self.assertNotIn('192.0.2.1', json.dumps(result))

    async def test_owned_session_is_closed(self):
        session = ProbeSession(Response({'code': 200, 'data': {'list': []}}))
        with patch('scanner_integration.key_probe.get_session', return_value=session):
            await probe_key('daydaymap', 'key', {})
        self.assertTrue(session.closed)


class KeyProbeRouteTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(scan_routes.scan_bp)
        self.client = app.test_client()

    def test_routes_only_requested_stored_key_by_id(self):
        bridge = types.SimpleNamespace(run_sync=lambda coro, timeout: asyncio.run(coro))
        requested_id = key_id('hunter', 'stored-second')
        with patch('scanner_integration.config_bridge.get_scan_config', return_value={'hunter_api_keys': ['first', 'stored-second']}), \
             patch.object(scan_routes, '_ensure_scan_bridge', return_value=(types.SimpleNamespace(bridge=bridge), None, 200)), \
             patch('scanner_integration.key_probe.probe_key', new_callable=AsyncMock, return_value={'usable': True}) as probe:
            response = self.client.post('/api/scan/keys/test', json={
                'platform': 'hunter', 'key_id': requested_id, 'key': 'client-supplied-ignored',
            })
        self.assertEqual(200, response.status_code)
        self.assertEqual(('hunter', 'stored-second'), probe.call_args.args[:2])
        self.assertNotIn('stored-second', response.get_data(as_text=True))
        self.assertEqual(requested_id, response.json['data']['key_id'])

    def test_invalid_deleted_and_concurrent_keys_never_issue_search(self):
        with patch('scanner_integration.key_probe.probe_key', new_callable=AsyncMock) as probe, \
             patch('scanner_integration.config_bridge.get_scan_config', return_value={'hunter_api_keys': []}):
            self.assertEqual(400, self.client.post('/api/scan/keys/test', json=[]).status_code)
            self.assertEqual(400, self.client.post('/api/scan/keys/test', json={'platform': 'other', 'key_id': 'x'}).status_code)
            self.assertEqual(404, self.client.post('/api/scan/keys/test', json={'platform': 'hunter', 'key_id': 'deleted'}).status_code)
            with patch.object(scan_routes, '_active_key_probes', {('hunter', 'busy')}):
                self.assertEqual(409, self.client.post('/api/scan/keys/test', json={'platform': 'hunter', 'key_id': 'busy'}).status_code)
            probe.assert_not_called()

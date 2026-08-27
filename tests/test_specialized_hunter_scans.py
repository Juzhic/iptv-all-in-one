import asyncio
import base64
import unittest
from unittest.mock import patch

import scanner_integration.platforms.iptv_interactive as iptv_interactive
import scanner_integration.platforms.tvheadend as tvheadend


class _EmptyHunterResponse:
    status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def json(self):
        return {'code': 200, 'data': {'arr': []}}


class _RecordingSession:
    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _EmptyHunterResponse()


def _decode_search(encoded):
    padding = '=' * (-len(encoded) % 4)
    return base64.urlsafe_b64decode(encoded + padding).decode()


class SpecializedHunterScanTests(unittest.TestCase):
    def _request_params(self, module, scan_func, target_size=30):
        session = _RecordingSession()
        with patch.object(module, 'API_REQUEST_DELAY', 0):
            result = asyncio.run(scan_func(
                'hunter-key', target_size=target_size, session=session,
            ))

        self.assertEqual([], result)
        self.assertEqual(1, len(session.calls))
        return session.calls[0][1]['params']

    def test_specialized_scans_respect_hunter_page_limit(self):
        scanners = (
            (tvheadend, tvheadend.tvheadend_scan),
            (iptv_interactive, iptv_interactive.iptv_interactive_scan),
        )

        for module, scan_func in scanners:
            with self.subTest(scanner=scan_func.__name__):
                params = self._request_params(module, scan_func)
                self.assertEqual(10, params['page_size'])

    def test_iptv_interactive_uses_hunter_title_field(self):
        params = self._request_params(
            iptv_interactive, iptv_interactive.iptv_interactive_scan,
        )

        self.assertEqual(
            'web.title:"首页 - IPTV互动电视系统"',
            _decode_search(params['search']),
        )


if __name__ == '__main__':
    unittest.main()

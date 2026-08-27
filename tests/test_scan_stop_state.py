import asyncio
import unittest
from unittest.mock import patch

from scanner_integration import config_bridge, scan_state
from scanner_integration.platforms import scan_state as platform_scan_state
from scanner_integration.platforms.daydaymap import daydaymap_scan
from scanner_integration.platforms.fofa import fofa_scan
from scanner_integration.platforms.hunter import hunter_scan
from scanner_integration.platforms.quake import quake_scan
from scanner_integration.platforms.shared import _is_stop_requested


class ScanStopStateTests(unittest.TestCase):
    def setUp(self):
        scan_state.clear_stop()

    def tearDown(self):
        scan_state.clear_stop()

    def test_platform_helper_reads_global_scan_state(self):
        self.assertFalse(_is_stop_requested())

        scan_state.request_stop()

        self.assertTrue(_is_stop_requested())

    def test_platform_package_reexports_global_scan_state(self):
        self.assertIs(platform_scan_state, scan_state)

    def test_enabled_api_scanners_honor_stop_before_network_access(self):
        scanners = (
            (quake_scan, ('key', 'query', 1)),
            (hunter_scan, ('key', 'query', 1)),
            (daydaymap_scan, ('key', 'query', 1)),
            (fofa_scan, ('key', 'query', 1)),
        )
        scan_state.request_stop()

        with patch.object(
                config_bridge, 'get_scan_config',
                return_value={
                    'enable_c_scan': False,
                    'fofa_email': 'test@example.com',
                }):
            for scanner, args in scanners:
                with self.subTest(scanner=scanner.__name__):
                    result = asyncio.run(scanner(*args, session=object()))
                    self.assertEqual([], result)


if __name__ == '__main__':
    unittest.main()

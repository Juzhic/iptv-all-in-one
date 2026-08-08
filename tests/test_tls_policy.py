import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


_MODULE_PATH = Path(__file__).resolve().parents[1] / 'engine' / 'ffmpeg_test.py'
_SPEC = importlib.util.spec_from_file_location('ffmpeg_test_under_test', _MODULE_PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


class TlsPolicyTests(unittest.TestCase):
    def test_certificate_failure_never_retries_without_verification(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(_MODULE.requests, 'get', side_effect=_MODULE.requests.exceptions.SSLError('bad cert')) as get:
            with self.assertRaises(_MODULE.requests.exceptions.SSLError):
                _MODULE.http_get('https://example.com/feed', timeout=3)
        self.assertEqual(1, get.call_count)
        self.assertTrue(get.call_args.kwargs['verify'])

    def test_explicit_exception_is_host_scoped_and_cannot_redirect(self):
        response = Mock(is_redirect=True)
        with patch.dict(os.environ, {'IPTV_INSECURE_TLS_HOSTS': 'legacy.example'}, clear=True), \
             patch.object(_MODULE.requests, 'get', return_value=response) as get:
            with self.assertRaises(_MODULE.requests.exceptions.SSLError):
                _MODULE.http_get('https://legacy.example/feed', timeout=3)
        self.assertFalse(get.call_args.kwargs['verify'])
        self.assertFalse(get.call_args.kwargs['allow_redirects'])
        response.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()

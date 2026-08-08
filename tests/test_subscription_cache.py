import threading
import time
import unittest
import importlib.util
from pathlib import Path

from flask import Flask, Response

_MODULE_PATH = Path(__file__).resolve().parents[1] / 'web' / 'subscription_cache.py'
_SPEC = importlib.util.spec_from_file_location('subscription_cache_under_test', _MODULE_PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
_reset_for_tests = _MODULE._reset_for_tests
anonymous_feed = _MODULE.anonymous_feed


class AnonymousFeedTests(unittest.TestCase):
    def setUp(self):
        _reset_for_tests()
        self.generated = 0
        self.counter_lock = threading.Lock()
        app = Flask(__name__)

        @app.get('/feed')
        @anonymous_feed
        def feed():
            with self.counter_lock:
                self.generated += 1
            time.sleep(0.02)
            return Response('playlist', content_type='audio/x-mpegurl')

        self.app = app

    def test_cache_and_etag(self):
        client = self.app.test_client()
        first = client.get('/feed')
        second = client.get('/feed')
        self.assertEqual(200, first.status_code)
        self.assertEqual(1, self.generated)
        self.assertEqual(first.headers['ETag'], second.headers['ETag'])
        conditional = client.get('/feed', headers={'If-None-Match': first.headers['ETag']})
        self.assertEqual(304, conditional.status_code)

    def test_generation_stampede_is_coalesced(self):
        statuses = []

        def fetch():
            with self.app.test_client() as client:
                statuses.append(client.get('/feed').status_code)

        threads = [threading.Thread(target=fetch) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual([200] * 6, sorted(statuses))
        self.assertEqual(1, self.generated)

    def test_sixty_requests_per_minute_limit(self):
        client = self.app.test_client()
        for _ in range(60):
            self.assertEqual(200, client.get('/feed').status_code)
        blocked = client.get('/feed')
        self.assertEqual(429, blocked.status_code)
        self.assertGreaterEqual(int(blocked.headers['Retry-After']), 1)


if __name__ == '__main__':
    unittest.main()

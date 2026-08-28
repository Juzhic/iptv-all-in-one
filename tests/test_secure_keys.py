import json
import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from scanner_integration.config_bridge import (
    _decrypt_stored_keys,
    _encrypt_persisted_keys,
    _normalize_scan_config,
    _prepare_persisted_config,
    migrate_stored_api_keys,
)
from scanner_integration.secure_keys import (
    CRYPTO_AVAILABLE,
    SecretConfigurationError,
    decrypt_api_key,
    encrypt_api_key,
    find_key_by_id,
    key_id,
    key_suffix,
    secret_is_configured,
)


class SecureKeyTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {"IPTV_SECRET_KEY": "test-secret-" + "x" * 48},
            clear=False,
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()

    @unittest.skipUnless(CRYPTO_AVAILABLE, "cryptography is not installed in this dev venv")
    def test_encrypt_round_trip_and_no_plaintext(self):
        token = encrypt_api_key("hunter-super-secret")
        self.assertTrue(token.startswith("enc:v1:"))
        self.assertNotIn("hunter-super-secret", token)
        self.assertEqual("hunter-super-secret", decrypt_api_key(token))

    def test_key_id_is_stable_scoped_and_resolvable(self):
        hunter_id = key_id("hunter", "alpha123456")
        self.assertEqual(hunter_id, key_id("hunter", "alpha123456"))
        self.assertNotEqual(hunter_id, key_id("quake", "alpha123456"))
        self.assertEqual((0, "alpha123456"), find_key_by_id("hunter", ["alpha123456"], hunter_id))
        self.assertEqual("123456", key_suffix("alpha123456"))

    def test_legacy_key_id_works_without_application_secret(self):
        with patch.dict(os.environ, {"IPTV_SECRET_KEY": ""}, clear=False):
            first = key_id("hunter", "alpha123456")
            self.assertFalse(secret_is_configured())
            self.assertTrue(first.startswith("kid_"))
            self.assertEqual(first, key_id("hunter", "alpha123456"))
            self.assertEqual(
                (0, "alpha123456"),
                find_key_by_id("hunter", ["alpha123456"], first),
            )

    def test_plaintext_keys_remain_readable_without_secret(self):
        with patch.dict(os.environ, {"IPTV_SECRET_KEY": ""}, clear=False):
            restored, migrate = _decrypt_stored_keys({
                "quake_api_keys": ["legacy-plain-key"],
            })
            self.assertTrue(migrate)
            self.assertEqual(["legacy-plain-key"], restored["quake_api_keys"])

    def test_legacy_config_save_stays_plaintext_without_secret(self):
        with patch.dict(os.environ, {"IPTV_SECRET_KEY": ""}, clear=False):
            runtime = _normalize_scan_config({
                "quake_api_keys": ["legacy-plain-key"],
                "quake_size": 321,
            })
            stored = _prepare_persisted_config(runtime)
            self.assertEqual(["legacy-plain-key"], stored["quake_api_keys"])
            self.assertEqual("legacy-plain-key", stored["quake_api_key"])
            self.assertEqual(321, stored["quake_size"])
            self.assertNotIn("quake_key", stored)

    @unittest.skipUnless(CRYPTO_AVAILABLE, "cryptography is not installed in this dev venv")
    def test_legacy_key_migration_is_transactional(self):
        class FakeConnection:
            def __init__(self):
                self.events = []
                self.queries = []
                self.updated = None

            @contextmanager
            def transaction(self):
                self.events.append('begin')
                try:
                    yield self
                except BaseException:
                    self.events.append('rollback')
                    raise
                self.events.append('commit')

            def execute(self, query, args=None):
                self.events.append(query.split()[0].lower())
                self.queries.append(query)
                if query.startswith('SELECT'):
                    return type('Cursor', (), {
                        'fetchone': lambda _self: {
                            'content': json.dumps({
                                'quake_api_keys': ['legacy-plain-key'],
                            }),
                        },
                    })()
                self.updated = args[0]
                return type('Cursor', (), {})()

        import database.db as database_db
        connection = FakeConnection()
        with (
            patch.dict(os.environ, {"IPTV_SECRET_KEY": "migration-secret-" + "x" * 40}),
            patch.object(database_db, '_get_conn', return_value=connection),
            patch.object(database_db, 'now_str', return_value='2026-08-12 12:00:00'),
        ):
            self.assertTrue(migrate_stored_api_keys())

        self.assertEqual(['begin', 'select', 'update', 'commit'], connection.events)
        self.assertTrue(all('`key`' not in query for query in connection.queries))
        self.assertTrue(all('"key"' in query for query in connection.queries))
        self.assertNotIn('legacy-plain-key', connection.updated)
        stored = json.loads(connection.updated)
        self.assertTrue(stored['quake_api_keys'][0].startswith('enc:v1:'))

    @unittest.skipUnless(CRYPTO_AVAILABLE, "cryptography is not installed in this dev venv")
    def test_config_storage_encrypts_all_legacy_key_fields(self):
        runtime = _normalize_scan_config({"hunter_api_keys": ["one", "two"]})
        stored = _encrypt_persisted_keys(runtime)
        self.assertTrue(all(v.startswith("enc:v1:") for v in stored["hunter_api_keys"]))
        self.assertTrue(stored["hunter_api_key"].startswith("enc:v1:"))
        restored, migrate = _decrypt_stored_keys(stored)
        self.assertFalse(migrate)
        self.assertEqual(["one", "two"], restored["hunter_api_keys"])

    def test_plaintext_requires_strong_secret_for_migration(self):
        with patch.dict(os.environ, {"IPTV_SECRET_KEY": "short"}, clear=False):
            with self.assertRaises(SecretConfigurationError):
                _encrypt_persisted_keys(_normalize_scan_config({"quake_api_keys": ["legacy"]}))


if __name__ == "__main__":
    unittest.main()

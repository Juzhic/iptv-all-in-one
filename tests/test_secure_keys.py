import os
import unittest
from unittest.mock import patch

from scanner_integration.config_bridge import (
    _decrypt_stored_keys,
    _encrypt_persisted_keys,
    _normalize_scan_config,
)
from scanner_integration.secure_keys import (
    CRYPTO_AVAILABLE,
    SecretConfigurationError,
    decrypt_api_key,
    encrypt_api_key,
    find_key_by_id,
    key_id,
    key_suffix,
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

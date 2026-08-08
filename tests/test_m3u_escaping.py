import importlib.util
import unittest
from pathlib import Path


_MODULE_PATH = Path(__file__).resolve().parents[1] / 'web' / 'result_gen.py'
_SPEC = importlib.util.spec_from_file_location('result_gen_under_test', _MODULE_PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


class M3uEscapingTests(unittest.TestCase):
    def test_attribute_escaping_blocks_quote_and_line_injection(self):
        escaped = _MODULE._sanitize_m3u_attr('name" group-title="evil\r\n#EXTM3U')
        self.assertNotIn('\r', escaped)
        self.assertNotIn('\n', escaped)
        self.assertNotIn('"', escaped)
        self.assertIn('&quot;', escaped)

    def test_playlist_lines_drop_all_control_characters(self):
        self.assertEqual('ab', _MODULE._sanitize_playlist_line('a\x00\tb\r\n'))


if __name__ == '__main__':
    unittest.main()

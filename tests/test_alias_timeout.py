import unittest

from engine.alias import match_channel_name, reset_regex_timeout_rules


class _TimeoutPattern:
    def __init__(self):
        self.calls = 0

    def match(self, _value, timeout=None):
        self.calls += 1
        self.timeout = timeout
        raise TimeoutError("catastrophic backtracking")

    def __str__(self):
        return "(a+)+$"


class AliasTimeoutTests(unittest.TestCase):
    def setUp(self):
        reset_regex_timeout_rules()

    def test_timeout_disables_rule_for_current_round(self):
        pattern = _TimeoutPattern()
        rules = [(pattern, "CCTV-1")]
        self.assertIsNone(match_channel_name("a" * 200 + "!", {}, rules))
        self.assertEqual(0.05, pattern.timeout)
        self.assertIsNone(match_channel_name("a" * 10, {}, rules))
        self.assertEqual(1, pattern.calls)

    def test_channel_name_length_is_bounded(self):
        pattern = _TimeoutPattern()
        self.assertIsNone(match_channel_name("x" * 257, {}, [(pattern, "CCTV-1")]))
        self.assertEqual(0, pattern.calls)


if __name__ == "__main__":
    unittest.main()

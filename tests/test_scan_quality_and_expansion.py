import asyncio
import importlib.util
import sys
import types
import unittest
from datetime import datetime


# The unit tests exercise pure scanner policy helpers.  Keep them runnable in
# lightweight CI images that do not install optional HTTP/database packages.
if importlib.util.find_spec('aiohttp') is None:
    aiohttp_stub = types.ModuleType('aiohttp')
    aiohttp_stub.ClientError = type('ClientError', (Exception,), {})
    aiohttp_stub.ClientTimeout = object
    aiohttp_stub.ClientSession = object
    aiohttp_stub.TCPConnector = object
    aiohttp_stub.DummyCookieJar = object
    resolver_stub = types.ModuleType('aiohttp.resolver')
    resolver_stub.ThreadedResolver = object
    sys.modules['aiohttp'] = aiohttp_stub
    sys.modules['aiohttp.resolver'] = resolver_stub

if 'database' not in sys.modules:
    database_stub = types.ModuleType('database')
    database_stub.local_now = datetime.now
    sys.modules['database'] = database_stub

if 'engine' not in sys.modules:
    engine_stub = types.ModuleType('engine')
    engine_stub.__path__ = []
    alias_stub = types.ModuleType('engine.alias')
    alias_stub.normalize_cctv_variant = lambda value: value
    alias_stub.strip_quality_suffix = lambda value: value
    alias_stub.match_channel_name = lambda value: None
    engine_stub.alias = alias_stub
    sys.modules['engine'] = engine_stub
    sys.modules['engine.alias'] = alias_stub

from scanner_integration.isp_intelligence import _build_quality_hotspot_candidates
from scanner_integration.platforms.ip_extract import CScanBudget, _TTLCache
from scanner_integration.video_check import quality_gate_failure


QUALITY_THRESHOLDS = {
    'stability_high': 60,
    'stability_low': 30,
    'max_delay_ms': 2000,
    'min_bandwidth_MBps': 0.3,
}


class QualityGateTests(unittest.TestCase):
    def test_low_bandwidth_is_rejected_even_when_stable(self):
        reason = quality_gate_failure({
            'bandwidth': 0.299,
            'delay': 80,
            'stability': 95,
        }, QUALITY_THRESHOLDS)

        self.assertEqual('low_bandwidth', reason)

    def test_qualifying_stream_is_accepted(self):
        reason = quality_gate_failure({
            'bandwidth': 0.5,
            'delay': 250,
            'stability': 75,
        }, QUALITY_THRESHOLDS)

        self.assertIsNone(reason)


class CSegmentBudgetTests(unittest.TestCase):
    def _budget(self):
        return CScanBudget({
            'c_segment_max_segments': 2,
            'c_segment_max_total_ips': 4,
            'c_segment_per_source_max_segments': 2,
            'c_segment_per_source_max_ips': 4,
        }, cache=_TTLCache(ttl=300, max_size=20))

    def test_global_ip_and_segment_budget_is_never_exceeded(self):
        async def run():
            budget = self._budget()
            selected, summary = await budget.reserve('source-a', [
                ('1.1.1', 80, ['1', '2', '3']),
                ('1.1.2', 80, ['4', '5', '6']),
            ])
            overflow, _ = await budget.reserve('source-b', [
                ('1.1.3', 80, ['7', '8']),
            ])
            return budget, selected, summary, overflow

        budget, selected, summary, overflow = asyncio.run(run())
        self.assertEqual(4, len(selected))
        self.assertEqual(2, summary['segments'])
        self.assertEqual(2, budget.segments_used)
        self.assertEqual(4, budget.ips_used)
        self.assertEqual([], overflow)

    def test_cache_distinguishes_ports(self):
        async def run():
            budget = self._budget()
            first, _ = await budget.reserve('source-a', [('2.2.2', 80, ['a'])])
            duplicate, duplicate_summary = await budget.reserve(
                'source-b', [('2.2.2', 80, ['b'])]
            )
            other_port, _ = await budget.reserve(
                'source-b', [('2.2.2', 8080, ['c'])]
            )
            return first, duplicate, duplicate_summary, other_port

        first, duplicate, duplicate_summary, other_port = asyncio.run(run())
        self.assertEqual([('a', 80)], first)
        self.assertEqual([], duplicate)
        self.assertEqual(1, duplicate_summary['cache_skipped'])
        self.assertEqual([('c', 8080)], other_port)


class QualityHotspotCandidateTests(unittest.TestCase):
    def test_first_round_covers_multiple_hotspot_segments(self):
        hot_segments = [
            {'segment': '10.0.1', 'hosts': ['10.0.1.10'], 'ports': [80]},
            {'segment': '10.0.2', 'hosts': ['10.0.2.10'], 'ports': [80]},
            {'segment': '10.0.3', 'hosts': ['10.0.3.10'], 'ports': [80]},
        ]

        candidates, covered = _build_quality_hotspot_candidates(
            hot_segments, limit=3, default_ports=[]
        )

        self.assertEqual(3, len(candidates))
        self.assertEqual(3, covered)
        self.assertEqual(
            {'10.0.1', '10.0.2', '10.0.3'},
            {item['segment'] for _, _, item in candidates},
        )


if __name__ == '__main__':
    unittest.main()

import asyncio
import unittest

from scanner_integration.safe_http import (
    NetworkPolicyError,
    PinnedResolver,
    ResponseTooLarge,
    read_response_limited,
    validate_http_url,
    validate_ip_address,
    validate_resolved_addresses,
)


class _FakeContent:
    def __init__(self, chunks):
        self.chunks = chunks

    async def iter_chunked(self, _size):
        for chunk in self.chunks:
            yield chunk


class _FakeResponse:
    def __init__(self, chunks, declared=None):
        self.headers = {} if declared is None else {"Content-Length": str(declared)}
        self.content = _FakeContent(chunks)


class SafeHttpPolicyTests(unittest.TestCase):
    def test_public_policy_blocks_private_and_metadata_addresses(self):
        for address in (
            "127.0.0.1", "10.0.0.1", "169.254.169.254",
            "100.100.100.200", "168.63.129.16",
        ):
            with self.subTest(address=address):
                with self.assertRaises(NetworkPolicyError):
                    validate_ip_address(address)

    def test_ip_scan_policy_allows_only_rfc1918_special_ranges(self):
        self.assertEqual("192.168.1.8", validate_ip_address("192.168.1.8", allow_rfc1918=True))
        for address in ("127.0.0.1", "169.254.2.1", "224.0.0.1", "0.0.0.0"):
            with self.subTest(address=address):
                with self.assertRaises(NetworkPolicyError):
                    validate_ip_address(address, allow_rfc1918=True)

    def test_dns_rebinding_mixed_answer_is_rejected(self):
        with self.assertRaises(NetworkPolicyError):
            validate_resolved_addresses("example.com", ["8.8.8.8", "127.0.0.1"])

    def test_pinned_resolver_never_performs_a_second_dns_lookup(self):
        resolver = PinnedResolver("example.com", ["8.8.8.8"])
        records = asyncio.run(resolver.resolve("example.com", 443))
        self.assertEqual(["8.8.8.8"], [record["host"] for record in records])
        with self.assertRaises(OSError):
            asyncio.run(resolver.resolve("redirect.example", 443))

    def test_redirect_destinations_must_remain_http_urls(self):
        self.assertEqual(("example.com", None), validate_http_url("https://example.com/path"))
        for url in ("file:///etc/passwd", "gopher://example.com", "https://metadata.google.internal/"):
            with self.subTest(url=url):
                with self.assertRaises(NetworkPolicyError):
                    validate_http_url(url)

    def test_decompressed_response_limit_is_enforced(self):
        with self.assertRaises(ResponseTooLarge):
            asyncio.run(read_response_limited(_FakeResponse([b"a" * 6, b"b" * 6]), 10))
        with self.assertRaises(ResponseTooLarge):
            asyncio.run(read_response_limited(_FakeResponse([], declared=11), 10))


if __name__ == "__main__":
    unittest.main()

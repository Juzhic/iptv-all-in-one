# -*- coding: utf-8 -*-
"""Bounded HTTP client with SSRF, redirect and DNS-rebinding protection."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import socket
import time
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urljoin, urlsplit

import aiohttp
from aiohttp.abc import AbstractResolver


logger = logging.getLogger("iptv_safe_http")

DEFAULT_MAX_RESPONSE_BYTES = 1024 * 1024
MAX_REDIRECTS = 3
ALLOWED_SCHEMES = {"http", "https"}
REDIRECT_STATUSES = {301, 302, 303, 307, 308}

_RFC1918 = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
)
_METADATA_IPS = {
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("100.100.100.200"),
    ipaddress.ip_address("168.63.129.16"),
    ipaddress.ip_address("fd00:ec2::254"),
}
_METADATA_HOSTS = {
    "metadata",
    "metadata.google.internal",
    "metadata.google",
    "metadata.azure.internal",
    "metadata.tencentyun.com",
    "instance-data",
}


class NetworkPolicyError(ValueError):
    """The requested destination violates the selected network policy."""


class ResponseTooLarge(NetworkPolicyError):
    """A remote body exceeded the configured decompressed byte limit."""


async def read_response_limited(
    response: aiohttp.ClientResponse,
    max_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
) -> bytes:
    """Read an aiohttp body with a decompressed byte ceiling."""
    content_length = response.headers.get("Content-Length")
    if content_length:
        try:
            declared_length = int(content_length)
        except ValueError:
            declared_length = 0
        if declared_length > max_bytes:
            raise ResponseTooLarge(f"响应内容超过 {max_bytes} 字节")
    chunks = []
    total = 0
    async for chunk in response.content.iter_chunked(65536):
        total += len(chunk)
        if total > max_bytes:
            raise ResponseTooLarge(f"响应内容超过 {max_bytes} 字节")
        chunks.append(chunk)
    return b"".join(chunks)


@dataclass(frozen=True)
class SafeResponse:
    status: int
    headers: dict[str, str]
    body: bytes
    url: str
    peer_ip: str
    elapsed_ms: float

    def text(self, encoding: str | None = None) -> str:
        charset = encoding
        if not charset:
            content_type = self.headers.get("Content-Type", "")
            marker = "charset="
            if marker in content_type.lower():
                charset = content_type.lower().split(marker, 1)[1].split(";", 1)[0].strip()
        return self.body.decode(charset or "utf-8", errors="replace")


def _normalize_ip(value: str):
    parsed = ipaddress.ip_address(str(value).split("%", 1)[0])
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped:
        return parsed.ipv4_mapped
    return parsed


def _is_rfc1918(value) -> bool:
    return any(value in network for network in _RFC1918)


def validate_ip_address(value: str, *, allow_rfc1918: bool = False) -> str:
    """Validate a resolved address and return its canonical string."""
    try:
        parsed = _normalize_ip(value)
    except ValueError as exc:
        raise NetworkPolicyError("目标地址不是有效 IP") from exc

    if parsed in _METADATA_IPS:
        raise NetworkPolicyError("禁止访问云元数据地址")
    if parsed.is_loopback:
        raise NetworkPolicyError("禁止访问回环地址")
    if parsed.is_link_local:
        raise NetworkPolicyError("禁止访问链路本地地址")
    if parsed.is_multicast:
        raise NetworkPolicyError("禁止访问组播地址")
    if parsed.is_unspecified:
        raise NetworkPolicyError("禁止访问未指定地址")

    if allow_rfc1918 and _is_rfc1918(parsed):
        return str(parsed)
    if not parsed.is_global:
        raise NetworkPolicyError("目标必须是公网地址")
    return str(parsed)


def validate_host_name(host: str) -> str:
    """Reject metadata aliases, control characters and malformed hosts."""
    normalized = (host or "").strip().rstrip(".").lower()
    if not normalized or any(ord(ch) < 32 or ord(ch) == 127 for ch in normalized):
        raise NetworkPolicyError("目标主机名无效")
    if normalized in _METADATA_HOSTS or normalized.endswith(".metadata.google.internal"):
        raise NetworkPolicyError("禁止访问云元数据主机")
    return normalized


def validate_http_url(url: str) -> tuple[str, int | None]:
    """Validate HTTP(S) URL syntax and return ``(host, port)``."""
    if not isinstance(url, str) or len(url) > 4096:
        raise NetworkPolicyError("URL 长度必须在 1 到 4096 字符之间")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in url):
        raise NetworkPolicyError("URL 不能包含控制字符")
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES or not parsed.hostname:
        raise NetworkPolicyError("仅允许完整的 HTTP(S) URL")
    host = validate_host_name(parsed.hostname)
    try:
        port = parsed.port
    except ValueError as exc:
        raise NetworkPolicyError("URL 端口无效") from exc
    return host, port


def validate_resolved_addresses(
    host: str,
    addresses: Iterable[str],
    *,
    allow_rfc1918: bool = False,
) -> tuple[str, ...]:
    """Validate every DNS answer; mixed public/private answers are rejected."""
    validate_host_name(host)
    validated = []
    for address in addresses:
        canonical = validate_ip_address(address, allow_rfc1918=allow_rfc1918)
        if canonical not in validated:
            validated.append(canonical)
    if not validated:
        raise NetworkPolicyError("目标主机没有可用地址")
    return tuple(validated)


async def _resolve_host(host: str, port: int) -> tuple[str, ...]:
    try:
        # IP literals must not be sent through DNS.
        return (str(_normalize_ip(host)),)
    except ValueError:
        pass
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(
            host,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise NetworkPolicyError("目标主机 DNS 解析失败") from exc
    return tuple(info[4][0] for info in infos)


class PinnedResolver(AbstractResolver):
    """aiohttp resolver that can only return pre-validated addresses."""

    def __init__(self, host: str, addresses: Iterable[str]):
        self.host = host.lower().rstrip(".")
        self.addresses = tuple(addresses)

    async def resolve(self, host, port=0, family=socket.AF_INET):
        if host.lower().rstrip(".") != self.host:
            raise OSError("unpinned hostname")
        records = []
        for address in self.addresses:
            parsed = _normalize_ip(address)
            records.append({
                "hostname": host,
                "host": str(parsed),
                "port": port,
                "family": socket.AF_INET6 if parsed.version == 6 else socket.AF_INET,
                "proto": 0,
                "flags": socket.AI_NUMERICHOST,
            })
        return records

    async def close(self):
        return None


def _configured_insecure_tls_hosts() -> set[str]:
    return {
        item.strip().lower().rstrip(".")
        for item in os.environ.get("IPTV_INSECURE_TLS_HOSTS", "").split(",")
        if item.strip()
    }


def _peer_ip(response: aiohttp.ClientResponse) -> str:
    connection = response.connection
    transport = connection.transport if connection is not None else None
    peer = transport.get_extra_info("peername") if transport is not None else None
    if not peer:
        raise NetworkPolicyError("无法核对远端实际 IP")
    return str(_normalize_ip(peer[0]))


async def safe_fetch(
    url: str,
    *,
    method: str = "GET",
    headers: dict | None = None,
    timeout: float = 15,
    max_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    max_redirects: int = MAX_REDIRECTS,
    allow_rfc1918: bool = False,
) -> SafeResponse:
    """Fetch one bounded response while validating and pinning every hop."""
    if method.upper() not in {"GET", "HEAD"}:
        raise ValueError("safe_fetch only supports GET and HEAD")
    if not 1 <= int(max_bytes) <= 5 * 1024 * 1024:
        raise ValueError("max_bytes must be between 1 and 5 MiB")
    if not 0 <= int(max_redirects) <= MAX_REDIRECTS:
        raise ValueError("max_redirects must be between 0 and 3")

    current_url = url
    started = time.monotonic()
    for hop in range(max_redirects + 1):
        host, explicit_port = validate_http_url(current_url)
        scheme = urlsplit(current_url).scheme.lower()
        port = explicit_port or (443 if scheme == "https" else 80)
        resolved = validate_resolved_addresses(
            host,
            await _resolve_host(host, port),
            allow_rfc1918=allow_rfc1918,
        )
        connector = aiohttp.TCPConnector(
            resolver=PinnedResolver(host, resolved),
            use_dns_cache=False,
            limit=1,
            limit_per_host=1,
            enable_cleanup_closed=True,
        )
        insecure_tls = scheme == "https" and host in _configured_insecure_tls_hosts()
        if insecure_tls:
            logger.warning("管理员已为主机 %s 启用不安全 TLS 例外", host)
        timeout_config = aiohttp.ClientTimeout(total=timeout, connect=min(timeout, 5))
        async with aiohttp.ClientSession(
            connector=connector,
            timeout=timeout_config,
            cookie_jar=aiohttp.DummyCookieJar(),
            auto_decompress=True,
        ) as session:
            async with session.request(
                method.upper(),
                current_url,
                headers=headers,
                allow_redirects=False,
                ssl=False if insecure_tls else True,
            ) as response:
                peer_ip = _peer_ip(response)
                validate_ip_address(peer_ip, allow_rfc1918=allow_rfc1918)
                if peer_ip not in resolved:
                    raise NetworkPolicyError("实际连接 IP 与已验证 DNS 结果不一致")

                if response.status in REDIRECT_STATUSES:
                    location = response.headers.get("Location", "").strip()
                    if not location:
                        raise NetworkPolicyError("重定向响应缺少 Location")
                    if hop >= max_redirects:
                        raise NetworkPolicyError("重定向次数超过限制")
                    current_url = urljoin(current_url, location)
                    validate_http_url(current_url)
                    continue

                body = b"" if method.upper() == "HEAD" else await read_response_limited(
                    response, max_bytes=max_bytes
                )
                return SafeResponse(
                    status=response.status,
                    headers=dict(response.headers),
                    body=body,
                    url=str(response.url),
                    peer_ip=peer_ip,
                    elapsed_ms=round((time.monotonic() - started) * 1000, 2),
                )
    raise NetworkPolicyError("重定向次数超过限制")

import ipaddress
import logging
import re as _re
import socket
import time
from urllib.parse import urlparse

import requests

from engine import load_config

logger = logging.getLogger('iptv_notify')


def _validate_webhook_url(url):
    """Validate webhook URL to prevent SSRF with DNS rebinding protection.

    Returns (parsed_url, pinned_ip) on success, None on failure.
    The pinned IP ensures the resolved address is reused for the actual request,
    preventing a TOCTOU race where DNS could re-resolve to a private IP.
    """
    if not url:
        return None
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ('https', 'http'):
            return None
        hostname = parsed.hostname
        if not hostname:
            return None
        if hostname in ('localhost', '127.0.0.1', '0.0.0.0', '::1', '[::1]'):
            return None
        try:
            infos = socket.getaddrinfo(hostname, None, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
            for family, _, _, _, sockaddr in infos:
                ip = ipaddress.ip_address(sockaddr[0])
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
                    return None
            # Pin the first resolved IP to prevent DNS rebinding
            return parsed, str(ipaddress.ip_address(infos[0][4][0]))
        except (socket.gaierror, ValueError, OSError):
            return None
    except (ValueError, TypeError, AttributeError):
        return None


def _build_pinned_url(parsed, pinned_ip):
    """Rewrite URL to use pinned IP with Host header for SSRF protection."""
    hostname = parsed.hostname
    port = parsed.port
    scheme = parsed.scheme
    netloc = pinned_ip
    if port:
        if (scheme == 'https' and port != 443) or (scheme == 'http' and port != 80):
            netloc = f"{pinned_ip}:{port}"
    return parsed._replace(netloc=netloc).geturl(), hostname


def _escape_md(text):
    """Escape Markdown special characters to prevent injection."""
    if not text:
        return text
    return _re.sub(r'([_*\[\]()~`>#+\-=|{}.!\\])', r'\\\1', str(text))


def _send_with_retry(send_func, url, title, content, headers=None, max_retries=3):
    """Send a webhook notification with exponential backoff retry."""
    for attempt in range(max_retries):
        try:
            send_func(url, title, content, headers=headers)
            return True
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                logger.warning(f"[Webhook] 发送失败(已重试{max_retries}次): {e}")
                return False


def send_webhook(event_type, title, content):
    """Send webhook notification. event_type: 'test', 'scan', 'detection'"""
    cfg = load_config()
    if not cfg.get('webhook_enabled'):
        return
    if not cfg.get('webhook_url'):
        return
    url = cfg['webhook_url']

    # Validate URL and pin resolved IP to prevent DNS rebinding (TOCTOU fix)
    result = _validate_webhook_url(url)
    if not result:
        return
    parsed, pinned_ip = result
    pinned_url, hostname = _build_pinned_url(parsed, pinned_ip)
    headers = {'Host': hostname}

    # Check if this event type is enabled
    if event_type == 'test' and not cfg.get('webhook_on_test', True):
        return
    if event_type == 'scan' and not cfg.get('webhook_on_scan', True):
        return
    if event_type == 'detection' and not cfg.get('webhook_on_detection', False):
        return

    # Escape Markdown in user-derived content to prevent injection
    safe_title = _escape_md(title)
    safe_content = _escape_md(content)

    wh_type = cfg.get('webhook_type', 'wecom')

    sent = False
    if wh_type == 'wecom':
        sent = _send_with_retry(_send_wecom, pinned_url, safe_title, safe_content, headers=headers)
    elif wh_type == 'dingtalk':
        sent = _send_with_retry(_send_dingtalk, pinned_url, safe_title, safe_content, headers=headers)
    elif wh_type == 'telegram':
        sent = _send_with_retry(_send_telegram, pinned_url, safe_title, safe_content, headers=headers)
    elif wh_type == 'serverchan':
        sent = _send_with_retry(_send_serverchan, pinned_url, safe_title, safe_content, headers=headers)
    if sent:
        logger.info(f"[Webhook] {wh_type} 通知已发送: {title}")
    else:
        logger.warning(f"[Webhook] {wh_type} 通知发送失败: {title}")


def _send_wecom(url, title, content, headers=None):
    resp = requests.post(url, json={
        "msgtype": "markdown",
        "markdown": {"content": f"### {title}\n{content}"}
    }, timeout=10, headers=headers)
    resp.raise_for_status()


def _send_dingtalk(url, title, content, headers=None):
    resp = requests.post(url, json={
        "msgtype": "markdown",
        "markdown": {"title": title, "text": f"### {title}\n{content}"}
    }, timeout=10, headers=headers)
    resp.raise_for_status()


def _send_telegram(url, title, content, headers=None):
    resp = requests.post(url, json={
        "text": f"*{title}*\n{content}",
        "parse_mode": "Markdown"
    }, timeout=10, headers=headers)
    resp.raise_for_status()


def _send_serverchan(url, title, content, headers=None):
    # ServerChan URL format: https://sctapi.ftqq.com/<key>.send
    resp = requests.post(url, data={"title": title, "desp": content}, timeout=10, headers=headers)
    resp.raise_for_status()

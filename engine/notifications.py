import ipaddress
import logging
import socket
from urllib.parse import urlparse

import requests

from engine import load_config

logger = logging.getLogger('iptv_notify')


def _validate_webhook_url(url):
    """Validate webhook URL to prevent SSRF."""
    if not url:
        return False
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ('https', 'http'):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        if hostname in ('localhost', '127.0.0.1', '0.0.0.0', '::1', '[::1]'):
            return False
        try:
            infos = socket.getaddrinfo(hostname, None, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
            for family, _, _, _, sockaddr in infos:
                ip = ipaddress.ip_address(sockaddr[0])
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
                    return False
        except (socket.gaierror, ValueError, OSError):
            return False
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def send_webhook(event_type, title, content):
    """Send webhook notification. event_type: 'test', 'scan', 'detection'"""
    cfg = load_config()
    if not cfg.get('webhook_enabled'):
        return
    if not cfg.get('webhook_url'):
        return
    url = cfg['webhook_url']
    if not _validate_webhook_url(url):
        return
    
    # Check if this event type is enabled
    if event_type == 'test' and not cfg.get('webhook_on_test', True):
        return
    if event_type == 'scan' and not cfg.get('webhook_on_scan', True):
        return
    if event_type == 'detection' and not cfg.get('webhook_on_detection', False):
        return
    
    wh_type = cfg.get('webhook_type', 'wecom')
    
    try:
        if wh_type == 'wecom':
            _send_wecom(url, title, content)
        elif wh_type == 'dingtalk':
            _send_dingtalk(url, title, content)
        elif wh_type == 'telegram':
            _send_telegram(url, title, content)
        elif wh_type == 'serverchan':
            _send_serverchan(url, title, content)
        logger.info(f"[Webhook] {wh_type} 通知已发送: {title}")
    except Exception as e:
        logger.warning(f"[Webhook] 发送失败: {e}")

def _send_wecom(url, title, content):
    requests.post(url, json={
        "msgtype": "markdown",
        "markdown": {"content": f"### {title}\n{content}"}
    }, timeout=10)

def _send_dingtalk(url, title, content):
    requests.post(url, json={
        "msgtype": "markdown",
        "markdown": {"title": title, "text": f"### {title}\n{content}"}
    }, timeout=10)

def _send_telegram(url, title, content):
    requests.post(url, json={
        "text": f"*{title}*\n{content}",
        "parse_mode": "Markdown"
    }, timeout=10)

def _send_serverchan(url, title, content):
    # ServerChan URL format: https://sctapi.ftqq.com/<key>.send
    requests.get(url, params={"title": title, "desp": content}, timeout=10)

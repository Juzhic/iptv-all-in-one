import importlib.util
import io
from pathlib import Path
import sys
import threading
import time
import types
from urllib.parse import parse_qs, urlsplit

import pytest
import urllib3

from test_security_v2 import web_app_module, _auth_headers, _mutation_headers


def _load_modules():
    root = Path(__file__).resolve().parents[1]
    names = ('web', 'web.routes', 'web.playback_proxy', 'web.routes.player')
    saved = {name: sys.modules.get(name) for name in names}
    try:
        for name in ('web', 'web.routes'):
            package = types.ModuleType(name)
            package.__path__ = [str(root / name.replace('.', '/'))]
            sys.modules[name] = package
        loaded = []
        for name in names[2:]:
            spec = importlib.util.spec_from_file_location(name, root / (name.replace('.', '/') + '.py'))
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            loaded.append(module)
        return loaded
    finally:
        for name, value in saved.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


transport, player = _load_modules()


@pytest.fixture
def app(monkeypatch):
    monkeypatch.delenv('IPTV_REQUIRE_STRONG_CREDENTIALS', raising=False)
    monkeypatch.delenv('IPTV_TRUSTED_ORIGINS', raising=False)
    app = web_app_module.create_app()
    app.config['TESTING'] = True
    app.register_blueprint(player.player_bp)
    monkeypatch.setattr(player, '_is_tested_url', lambda url: url == 'http://8.8.8.8/live/index.m3u8')
    monkeypatch.setattr(player, '_slots', threading.BoundedSemaphore(4))
    return app


def media_url(app, url='http://8.8.8.8/live/index.m3u8', kind='auto', expires=None):
    with app.test_request_context():
        return player._media_url(url, expires or int(time.time()) + 300, kind)


class Upstream:
    def __init__(self, body, content_type='video/mp2t', status=200, headers=None, url='http://8.8.8.8/live/index.m3u8'):
        self.response = urllib3.response.HTTPResponse(body=io.BytesIO(body), status=status,
            headers={'Content-Type': content_type, **(headers or {})}, preload_content=False)
        self.url = url
        self.closed = False

    def close(self):
        self.closed = True
        self.response.close()


def test_login_and_mutation_guard_protect_both_routes(app):
    client = app.test_client()
    assert client.post('/api/player/session', json={}).status_code == 401
    assert client.get(media_url(app)).status_code == 401
    assert client.post('/api/player/session', json={}, headers=_auth_headers()).status_code == 403
    assert client.post('/api/player/session', json={}, headers=_mutation_headers(Origin='https://evil.test')).status_code == 403


def test_session_only_signs_latest_passed_urls(app):
    client = app.test_client()
    result = client.post('/api/player/session', json={'url': 'http://8.8.8.8/live/index.m3u8', 'type': 'hls'}, headers=_mutation_headers())
    assert result.status_code == 200
    assert result.json['data']['url'].startswith('/api/player/stream?token=')
    assert client.post('/api/player/session', json={'url': 'http://8.8.4.4/arbitrary'}, headers=_mutation_headers()).status_code == 403
    for url in ('file:///etc/passwd', 'http://user:pass@8.8.8.8/live', None):
        assert client.post('/api/player/session', json={'url': url}, headers=_mutation_headers()).status_code == 400


def test_passed_lookup_matches_subscription_run_order(monkeypatch):
    calls = []
    class Connection:
        def execute(self, sql, params):
            calls.append((sql, params))
            return self
        def fetchone(self):
            return {'exists': 1}
    monkeypatch.setattr(player, '_get_conn', lambda: Connection())
    assert player._is_tested_url('http://8.8.8.8/live')
    assert 'ORDER BY finished_at DESC, id DESC' in calls[0][0]
    assert 'passed = 1 AND url = %s' in calls[0][0]
    assert calls[0][1] == ('http://8.8.8.8/live',)


def test_invalid_expired_or_modified_tokens_never_open_network(app, monkeypatch):
    def unexpected(*args):
        pytest.fail('invalid token opened network')
    monkeypatch.setattr(player, 'open_upstream', unexpected)
    for url in ('/api/player/stream?url=http://8.8.8.8', '/api/player/stream?token=invalid', media_url(app, expires=int(time.time()) - 1), media_url(app) + 'tampered'):
        assert app.test_client().get(url, headers=_auth_headers()).status_code == 403


def test_hls_rewrites_variants_segments_keys_maps_and_uses_final_url(app, monkeypatch):
    manifest = b'''#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,URI="//8.8.4.4/audio/list"
#EXT-X-KEY:METHOD=AES-128,URI="../key?k=1"
#EXT-X-MAP:URI="init.mp4",BYTERANGE="100@0"
#EXT-X-STREAM-INF:BANDWIDTH=1000000
child/index.m3u8?token=a,b
#EXTINF:2,
/segments/001.ts
#EXT-X-I-FRAME-STREAM-INF:BANDWIDTH=1000,URI="iframe.m3u8"
'''
    upstream = Upstream(manifest, content_type='text/plain', url='http://8.8.8.8/redirected/master')
    monkeypatch.setattr(player, 'open_upstream', lambda *args: upstream)
    response = app.test_client().get(media_url(app), headers=_auth_headers())
    assert response.status_code == 200
    assert response.mimetype == 'application/vnd.apple.mpegurl'
    text = response.get_data(as_text=True)
    import re
    tokens = re.findall(r'/api/player/stream\?token=([^"\s]+)', text)
    with app.app_context():
        targets = [player._serializer().loads(token)['url'] for token in tokens]
    assert targets == ['http://8.8.4.4/audio/list', 'http://8.8.8.8/key?k=1', 'http://8.8.8.8/redirected/init.mp4',
                       'http://8.8.8.8/redirected/child/index.m3u8?token=a,b', 'http://8.8.8.8/segments/001.ts',
                       'http://8.8.8.8/redirected/iframe.m3u8']
    assert 'http://' not in text
    assert upstream.closed


def test_stream_range_and_close_release_connection(app, monkeypatch):
    upstream = Upstream(b'0123456789', status=206, headers={'Content-Range': 'bytes 10-19/100', 'Accept-Ranges': 'bytes', 'Content-Length': '10'})
    calls = []
    def open_stream(url, byte_range):
        calls.append((url, byte_range))
        return upstream
    monkeypatch.setattr(player, 'open_upstream', open_stream)
    response = app.test_client().get(media_url(app), headers=_auth_headers(Range='bytes=10-19'), buffered=False)
    assert response.status_code == 206
    assert response.headers['Content-Range'] == 'bytes 10-19/100'
    assert response.headers['X-Accel-Buffering'] == 'no'
    assert response.data == b'0123456789'
    response.close()
    assert upstream.closed
    assert calls[0][1] == 'bytes=10-19'
    assert player._slots.acquire(blocking=False)
    player._slots.release()


def test_client_disconnect_before_full_read_releases_slot(app, monkeypatch):
    upstream = Upstream(b'x' * 200000)
    monkeypatch.setattr(player, 'open_upstream', lambda *args: upstream)
    response = app.test_client().get(media_url(app), headers=_auth_headers(), buffered=False)
    response.close()
    assert upstream.closed
    acquired = [player._slots.acquire(blocking=False) for _ in range(4)]
    assert all(acquired)
    for _ in acquired:
        player._slots.release()


@pytest.mark.parametrize('status,expected', [(404, 404), (403, 502), (500, 502), (416, 416)])
def test_upstream_failures_close_connection(app, monkeypatch, status, expected):
    upstream = Upstream(b'error', status=status)
    monkeypatch.setattr(player, 'open_upstream', lambda *args: upstream)
    response = app.test_client().get(media_url(app), headers=_auth_headers())
    assert response.status_code == expected
    assert upstream.closed


def test_limits_and_malformed_playlist(app, monkeypatch):
    client = app.test_client()
    assert client.get(media_url(app), headers=_auth_headers(Range='bytes=0-1,2-3')).status_code == 416
    monkeypatch.setattr(player, '_slots', threading.BoundedSemaphore(0))
    assert client.get(media_url(app), headers=_auth_headers()).status_code == 503
    monkeypatch.setattr(player, '_slots', threading.BoundedSemaphore(4))
    for body in (b'<html>not a playlist</html>', b'#EXTM3U\n' + b'x' * (1024 * 1024)):
        upstream = Upstream(body)
        monkeypatch.setattr(player, 'open_upstream', lambda *args: upstream)
        assert client.get(media_url(app, kind='hls'), headers=_auth_headers()).status_code == 502
        assert upstream.closed


@pytest.mark.parametrize('address', ['127.0.0.1', '10.0.0.1', '169.254.169.254', '::1', '::ffff:127.0.0.1', '100.100.100.200'])
def test_dns_policy_rejects_private_and_metadata(address, monkeypatch):
    monkeypatch.setattr(transport, '_resolve', lambda *args: [address])
    with pytest.raises(transport.NetworkPolicyError):
        transport.open_upstream('http://source.test/live')


def test_dns_pinning_tls_host_and_redirect_validation(monkeypatch):
    resolutions, pools = [], []
    def resolve(host, port):
        resolutions.append(host)
        return ['8.8.8.8'] if host == 'source.test' else ['127.0.0.1']
    class Pool:
        def __init__(self, address, port, **kwargs):
            self.address, self.options = address, kwargs
            self.closed = False
            pools.append(self)
        def urlopen(self, method, path, **kwargs):
            self.request = kwargs
            return urllib3.response.HTTPResponse(body=io.BytesIO(b''), status=302, headers={'Location': 'http://internal.test/key'}, preload_content=False)
        def close(self):
            self.closed = True
    monkeypatch.setattr(transport, '_resolve', resolve)
    monkeypatch.setattr(transport.urllib3, 'HTTPSConnectionPool', Pool)
    with pytest.raises(transport.NetworkPolicyError):
        transport.open_upstream('https://source.test/live')
    assert resolutions == ['source.test', 'internal.test']
    assert pools[0].address == '8.8.8.8'
    assert pools[0].options == {'assert_hostname': 'source.test', 'server_hostname': 'source.test'}
    assert pools[0].request['headers'] == {'Host': 'source.test', 'User-Agent': 'IPTV-Player/1.0', 'Accept-Encoding': 'identity'}
    assert pools[0].closed


def test_rewrite_drops_steering_and_preserves_inline_keys():
    manifest = '#EXTM3U\n#EXT-X-CONTENT-STEERING:SERVER-URI="https://other.test/steering"\n#EXT-X-KEY:METHOD=AES-128,URI="data:text/plain;base64,YQ=="\npart.ts\n'
    result = transport.rewrite_playlist(manifest, 'http://8.8.8.8/live', lambda url: '/proxy')
    assert 'CONTENT-STEERING' not in result
    assert 'data:text/plain;base64,YQ==' in result
    assert '/proxy' in result


def test_active_upstream_content_is_not_served_as_html(app, monkeypatch):
    upstream = Upstream(b'<script>alert(1)</script>', content_type='text/html')
    monkeypatch.setattr(player, 'open_upstream', lambda *args: upstream)
    response = app.test_client().get(media_url(app), headers=_auth_headers())
    assert response.mimetype == 'application/octet-stream'
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    response.close()


def test_real_http_hls_without_cors_works_through_authenticated_proxy(app, monkeypatch):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = {
                '/live/index.m3u8': b'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000\nchild.m3u8\n',
                '/live/child.m3u8': b'#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key"\n#EXTINF:2,\nsegment.ts\n',
                '/live/key': b'0123456789abcdef',
                '/live/segment.ts': b'\x47' * 188,
            }[self.path]
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # Only the fixture transport may reach this loopback server. Production
    # policy remains unchanged and is covered by the private-address tests.
    monkeypatch.setattr(transport, 'validate_resolved_addresses', lambda host, addresses: tuple(addresses))
    root = f'http://127.0.0.1:{server.server_port}/live/index.m3u8'
    monkeypatch.setattr(player, '_is_tested_url', lambda url: url == root)
    client = app.test_client()
    try:
        session = client.post('/api/player/session', json={'url': root, 'type': 'hls'}, headers=_mutation_headers())
        first = client.get(session.json['data']['url'], headers=_auth_headers())
        assert first.status_code == 200
        child = first.get_data(as_text=True).splitlines()[-1]
        second = client.get(child, headers=_auth_headers())
        text = second.get_data(as_text=True)
        import re
        key_url = re.search(r'URI="([^"]+)"', text)[1]
        key = client.get(key_url, headers=_auth_headers())
        segment = client.get(text.splitlines()[-1], headers=_auth_headers())
        assert key.data == b'0123456789abcdef'
        assert segment.data == b'\x47' * 188
        key.close()
        segment.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

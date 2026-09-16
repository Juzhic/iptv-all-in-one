"""Authenticated same-origin playback of tested subscriptions."""
import re
import logging
import threading
import time

from flask import Blueprint, Response, current_app, jsonify, request, url_for
from itsdangerous import BadData, URLSafeSerializer
import urllib3

from database import _get_conn
from scanner_integration.safe_http import NetworkPolicyError
from web.playback_proxy import HLS_TYPES, MAX_PLAYLIST_BYTES, open_upstream, rewrite_playlist, validate_playback_url

player_bp = Blueprint('player', __name__)
logger = logging.getLogger(__name__)
TOKEN_TTL = 12 * 60 * 60
# Leave capacity for control/API requests in the single-process threaded server.
_slots = threading.BoundedSemaphore(4)


def _serializer():
    return URLSafeSerializer(current_app.secret_key, salt='iptv-playback-v1')


def _media_url(url, expires, kind='auto'):
    return url_for('player.stream', token=_serializer().dumps({'url': url, 'expires': expires, 'kind': kind}))


def _is_tested_url(url):
    # Same run ordering as get_latest_passed_results / the M3U subscription.
    return _get_conn().execute(
        """SELECT 1 FROM run_results WHERE run_id =
           (SELECT run_id FROM runs ORDER BY finished_at DESC, id DESC LIMIT 1)
           AND passed = 1 AND url = %s LIMIT 1""", (url,)
    ).fetchone() is not None


@player_bp.post('/api/player/session')
def create_session():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(ok=False, error='播放参数必须为 JSON 对象'), 400
    url, kind = data.get('url'), data.get('type', 'auto')
    try:
        validate_playback_url(url)
    except (ValueError, TypeError):
        return jsonify(ok=False, error='播放代理仅支持有效的 HTTP(S) 线路地址'), 400
    if kind not in ('auto', 'hls', 'mpegts', 'flv', 'native'):
        return jsonify(ok=False, error='播放格式无效'), 400
    if not _is_tested_url(url):
        return jsonify(ok=False, error='线路不在最新测速通过结果中，请刷新订阅列表'), 403
    expires = int(time.time()) + TOKEN_TTL
    return jsonify(ok=True, data={'url': _media_url(url, expires, kind), 'expires': expires})


@player_bp.get('/api/player/stream')
def stream():
    token = request.args.get('token', '')
    try:
        if not token or len(token) > 12000:
            raise ValueError()
        payload = _serializer().loads(token)
        url, expires = payload['url'], payload['expires']
        if not isinstance(expires, int) or expires <= time.time():
            raise ValueError()
        validate_playback_url(url)
    except (BadData, ValueError, KeyError, TypeError):
        return jsonify(ok=False, error='播放地址无效或已过期，请重新播放'), 403
    range_header = request.headers.get('Range')
    if range_header and (len(range_header) > 100 or not re.fullmatch(r'bytes=(?:\d+-\d*|-\d+)', range_header)):
        return jsonify(ok=False, error='不支持的 Range 请求'), 416
    slots = _slots
    if not slots.acquire(blocking=False):
        return jsonify(ok=False, error='播放代理连接已满，请稍后重试'), 503, {'Retry-After': '2'}
    upstream = None
    released = False

    def close():
        nonlocal released
        if not released:
            released = True
            try:
                if upstream:
                    upstream.close()
            finally:
                slots.release()

    try:
        upstream = open_upstream(url, range_header)
        raw = upstream.response
        if raw.status not in (200, 206):
            status = raw.status if raw.status in (404, 416) else 502
            response = jsonify(ok=False, error=f'源站返回 HTTP {raw.status}，请切换线路')
            if raw.status == 416 and raw.headers.get('Content-Range'):
                response.headers['Content-Range'] = raw.headers['Content-Range']
            close()
            return response, status
        content_type = raw.headers.get('Content-Type', '').split(';')[0].lower()
        prefix = raw.read(16, decode_content=True)
        is_hls = payload.get('kind') == 'hls' or content_type in HLS_TYPES or prefix.lstrip(b'\xef\xbb\xbf\r\n ').startswith(b'#EXTM3U')
        headers = {'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'}
        if is_hls:
            body = bytearray(prefix)
            while chunk := raw.read(65536, decode_content=True):
                body.extend(chunk)
                if len(body) > MAX_PLAYLIST_BYTES:
                    raise ValueError('源站播放列表过大')
            content = rewrite_playlist(body.decode('utf-8-sig'), upstream.url, lambda child: _media_url(child, expires))
            close()
            return Response(content, content_type='application/vnd.apple.mpegurl', headers=headers)
        # Do not serve arbitrary source HTML/SVG/JS as active same-origin content.
        media_type = content_type if content_type.startswith(('video/', 'audio/')) else 'application/octet-stream'
        for name in ('Content-Range', 'Accept-Ranges'):
            if raw.headers.get(name):
                headers[name] = raw.headers[name]
        if raw.headers.get('Content-Length') and not raw.headers.get('Content-Encoding'):
            headers['Content-Length'] = raw.headers['Content-Length']

        def chunks():
            try:
                if prefix:
                    yield prefix
                yield from raw.stream(65536, decode_content=True)
            except (urllib3.exceptions.HTTPError, OSError):
                # Headers may already be sent. End the stream so the player can retry.
                logger.warning('播放源连接中断')
            finally:
                close()

        response = Response(chunks(), status=raw.status, content_type=media_type, headers=headers)
        response.call_on_close(close)
        return response
    except NetworkPolicyError:
        close()
        return jsonify(ok=False, error='播放代理仅允许公网 HTTP(S) 资源，源站或重定向目标不可访问'), 403
    except (urllib3.exceptions.HTTPError, OSError):
        close()
        return jsonify(ok=False, error='服务器连接播放源失败或超时，请切换线路'), 502
    except (ValueError, UnicodeError):
        close()
        return jsonify(ok=False, error='源站播放列表无效或暂不支持，请切换线路'), 502
    except Exception:
        close()
        raise

# -*- coding: utf-8 -*-
"""web 包 — 扫描模块 API 蓝图。"""
import asyncio
import logging
import time
from flask import Blueprint, request, jsonify, Response

import database as db
import web.state as _state
from web.app import _finite_number_or_none
from web.routes.params import int_arg
from web.routes.test_control import (
    SSE_MAX_DURATION_SECONDS,
    acquire_sse_slot,
)
from scanner_integration.safe_http import (
    DEFAULT_MAX_RESPONSE_BYTES,
    NetworkPolicyError,
    safe_fetch,
    validate_http_url,
)

logger = logging.getLogger(__name__)
SUPPORTED_KEY_PLATFORMS = ('quake', 'hunter', 'daydaymap', 'fofa')
_SCAN_RUNTIME_KEY_ALIASES = frozenset(
    ('quake_key', 'hunter_key', 'daydaymap_key', 'fofa_key')
)


def _is_scan_secret_field(name):
    return (
        name in _SCAN_RUNTIME_KEY_ALIASES
        or name.endswith('_api_key')
        or name.endswith('_api_keys')
    )


def _public_scan_config(cfg):
    """Return scanner settings without API keys or runtime secret aliases."""
    source = cfg if isinstance(cfg, dict) else {}
    public = {
        key: value for key, value in source.items()
        if not _is_scan_secret_field(str(key))
    }
    key_status = {}
    for platform in SUPPORTED_KEY_PLATFORMS:
        values = source.get(f'{platform}_api_keys', [])
        count = len(values) if isinstance(values, list) else 0
        if not count and source.get(f'{platform}_api_key'):
            count = 1
        key_status[platform] = {'has_keys': count > 0, 'count': count}
    public['key_status'] = key_status
    return public


def _strip_scan_secret_updates(data):
    if not isinstance(data, dict):
        return {}
    return {
        key: value for key, value in data.items()
        if not _is_scan_secret_field(str(key))
    }


def _validate_recheck_url(url):
    """Perform syntax/policy preflight; safe_fetch enforces resolved peers."""
    try:
        validate_http_url(url)
        return True, ''
    except NetworkPolicyError as exc:
        return False, str(exc)

scan_bp = Blueprint('scan', __name__)


def _get_scanner():
    """获取 scanner_integration 模块（启动时已导入，直接返回缓存引用）。"""
    return _state._scanner_module


def _ensure_scan_bridge():
    """确保扫描桥接层已初始化。"""
    scanner = _get_scanner()
    if scanner is None:
        return None, jsonify({'ok': False, 'error': '扫描模块依赖未安装，请先安装 aiohttp: pip install aiohttp'}), 503
    if scanner.bridge._loop is None or not scanner.bridge._loop.is_running():
        scanner.init_bridge()
    return scanner, None, None


def _scan_result_filters(args):
    return {
        'scan_id': args.get('scan_id') or None,
        'category': (args.get('category') or '').strip() or None,
        'province': (args.get('province') or '').strip() or None,
        'platform': (args.get('platform') or '').strip() or None,
        'search': (args.get('search') or '').strip()[:200] or None,
        'sort_by': (args.get('sort_by') or '').strip() or None,
        'sort_order': (args.get('sort_order') or 'desc').strip().lower(),
    }


def _one_line(value):
    return str(value or '').replace('\r', ' ').replace('\n', ' ').strip()


def _redact_value(value, secret):
    text = str(value or '')
    return text.replace(secret, '***') if secret else text


# ─────────────── 扫描控制 API ───────────────

@scan_bp.route('/api/scan/trigger', methods=['POST'])
def api_scan_trigger():
    """启动一次扫描。"""
    scanner, err, code = _ensure_scan_bridge()
    if err:
        return err, code
    data = request.get_json(silent=True) or {}
    result = scanner.trigger_scan(
        platforms=data.get('platforms'),
        provinces=data.get('provinces')
    )
    if 'error' in result:
        return jsonify({'ok': False, 'error': result['error']}), 409
    task = result.get('task') or {}
    return jsonify({
        'ok': True,
        'message': '扫描已启动',
        'task_id': task.get('task_id'),
        'state': 'starting',
        'data': result.get('task'),
    }), 202


@scan_bp.route('/api/scan/trigger-incremental', methods=['POST'])
def api_scan_trigger_incremental():
    """启动一次增量扫描（仅检查新源，跳过已知 URL）。"""
    scanner, err, code = _ensure_scan_bridge()
    if err:
        return err, code
    data = request.get_json(silent=True) or {}
    result = scanner.trigger_incremental_scan(
        platforms_override=data.get('platforms'),
        provinces_override=data.get('provinces')
    )
    if 'error' in result:
        return jsonify({'ok': False, 'error': result['error']}), 409
    task = result.get('task') or {}
    return jsonify({
        'ok': True,
        'message': '增量扫描已启动',
        'mode': 'incremental',
        'task_id': task.get('task_id'),
        'state': 'starting',
        'data': result.get('task'),
    }), 202


@scan_bp.route('/api/scan/stop', methods=['POST'])
def api_scan_stop():
    """请求停止扫描。"""
    scanner, err, code = _ensure_scan_bridge()
    if err:
        return err, code
    result = scanner.trigger_stop()
    if result.get('error'):
        return jsonify({'ok': False, 'error': result['error'], 'data': result.get('task')}), 409
    task = result.get('task') or {}
    return jsonify({
        'ok': True,
        'message': result.get('message', ''),
        'task_id': task.get('task_id'),
        'state': 'stopping',
        'data': result.get('task'),
    }), 202


@scan_bp.route('/api/scan/force-clear', methods=['POST'])
def api_scan_force_clear():
    """强制清除卡死的扫描状态。"""
    scanner = _get_scanner()
    if scanner is None:
        db.clear_scan_progress()
        return jsonify({'ok': True, 'message': '扫描状态已清除'})
    result = scanner.force_clear_scan()
    if result.get('error'):
        return jsonify({'ok': False, 'error': result['error'], 'data': result.get('task')}), 409
    return jsonify({'ok': True, 'data': result})


@scan_bp.route('/api/scan/status', methods=['GET'])
def api_scan_status():
    """获取扫描实时进度。"""
    scanner = _get_scanner()
    if scanner is None:
        return jsonify({'ok': True, 'data': {'running': False, 'phase': 'idle', 'message': '扫描模块未安装'}})
    status = scanner.get_scan_status()
    return jsonify({'ok': True, 'data': status})


@scan_bp.route('/api/scan/stream')
def api_scan_stream():
    """SSE 实时推送扫描进度和日志。"""
    scanner = _get_scanner()
    if scanner is None:
        return jsonify({'ok': False, 'error': '扫描模块未安装'}), 503
    slot = acquire_sse_slot()
    if slot is None:
        return jsonify({'ok': False, 'error': 'SSE 连接数已达上限'}), 429

    def generate():
        q = None
        deadline = time.monotonic() + SSE_MAX_DURATION_SECONDS
        try:
            q = scanner.subscribe_sse()
            # 立即发送当前状态
            import json
            status = scanner.get_scan_status()
            yield f"event: status\ndata: {json.dumps(status, ensure_ascii=False)}\n\n"
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    yield f"event: error\ndata: {json.dumps({'error': 'SSE 连接超时，请重新连接'})}\n\n"
                    break
                try:
                    msg = q.get(timeout=min(30, remaining))
                    yield msg
                except Exception:
                    yield ": heartbeat\n\n"
        except GeneratorExit:
            pass
        finally:
            if q is not None:
                scanner.unsubscribe_sse(q)
            slot.release()

    response = Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        }
    )
    response.call_on_close(slot.release)
    return response


@scan_bp.route('/api/scan/results', methods=['GET'])
def api_scan_results():
    """分页查询扫描结果。"""
    scanner = _get_scanner()
    if scanner is None:
        return jsonify({'ok': True, 'items': [], 'total': 0})
    page = int_arg(request.args, 'page', 1, 1, None)
    size = int_arg(request.args, 'size', 50, 1, 200)
    filters = _scan_result_filters(request.args)
    total, items = scanner.get_scan_results(
        page=page, size=size, **filters,
    )
    return jsonify({'ok': True, 'items': items, 'total': total, 'page': page, 'size': size})


@scan_bp.route('/api/scan/results/export', methods=['GET'])
def api_scan_results_export():
    """Stream every scan result matching the same filters as the table API."""
    scanner = _get_scanner()
    if scanner is None:
        return jsonify({'ok': False, 'error': '扫描模块未安装'}), 503
    output_format = (request.args.get('format') or 'm3u').strip().lower()
    if output_format not in ('txt', 'm3u'):
        return jsonify({'ok': False, 'error': 'format must be txt or m3u'}), 400
    filters = _scan_result_filters(request.args)

    def generate():
        page = 1
        emitted = 0
        try:
            if output_format == 'm3u':
                yield '#EXTM3U\n'
            while True:
                total, items = scanner.get_scan_results(
                    page=page, size=500, **filters,
                )
                if not items:
                    break
                for item in items:
                    name = _one_line(item.get('name')) or '未知频道'
                    url = _one_line(item.get('url'))
                    if not url:
                        continue
                    if output_format == 'm3u':
                        yield f'#EXTINF:-1,{name}\n{url}\n'
                    else:
                        yield f'{name},{url}\n'
                    emitted += 1
                if page * 500 >= total:
                    break
                page += 1
        finally:
            try:
                db._reset_thread_conn()
            except Exception:
                pass

    filename = f"scan_results.{output_format}"
    mimetype = 'audio/x-mpegurl' if output_format == 'm3u' else 'text/plain'
    return Response(
        generate(),
        mimetype=mimetype,
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


@scan_bp.route('/api/scan/latest', methods=['GET'])
def api_scan_latest():
    """获取最新扫描记录。"""
    scanner = _get_scanner()
    if scanner is None:
        return jsonify({'ok': True, 'data': None})
    return jsonify({'ok': True, 'data': scanner.get_latest_scan()})


@scan_bp.route('/api/scan/history', methods=['GET'])
def api_scan_history():
    """获取扫描历史。"""
    scanner = _get_scanner()
    if scanner is None:
        return jsonify({'ok': True, 'items': [], 'total': 0})
    limit = int_arg(request.args, 'limit', 50, 1, 200)
    items = scanner.get_scan_history(limit=limit)
    return jsonify({'ok': True, 'items': items, 'total': len(items)})


@scan_bp.route('/api/scan/config', methods=['GET'])
def api_scan_config_get():
    """读取扫描配置。"""
    try:
        scanner = _get_scanner()
        if scanner is not None:
            try:
                scanner.init_bridge()
            except Exception as e:
                logger.warning(f"[ScanConfig] 初始化扫描后台任务失败: {e}")
        from scanner_integration.config_bridge import get_scan_config
        cfg = get_scan_config()
        return jsonify({'ok': True, 'data': _public_scan_config(cfg)})
    except Exception:
        from scanner_integration.config_bridge import DEFAULT_SCAN_CONFIG
        return jsonify({'ok': True, 'data': _public_scan_config(DEFAULT_SCAN_CONFIG)})


@scan_bp.route('/api/scan/config', methods=['POST'])
def api_scan_config_set():
    """保存扫描配置。"""
    try:
        from scanner_integration.config_bridge import save_scan_config, get_scan_config
        from scanner_integration.key_manager import init_key_manager
        data = request.get_json(silent=True) or {}
        save_scan_config(_strip_scan_secret_updates(data))
        init_key_manager()
        scanner = _get_scanner()
        if scanner is not None:
            try:
                scanner.init_bridge()
                scanner.notify_scan_config_changed()
            except Exception as e:
                logger.warning(f"[ScanConfig] 重载定时扫描配置失败: {e}")
        cfg = get_scan_config()
        return jsonify({'ok': True, 'data': _public_scan_config(cfg)})
    except Exception as e:
        return jsonify({'ok': False, 'error': f'保存失败: {e}'}), 500


@scan_bp.route('/api/scan/keys', methods=['GET'])
def api_scan_keys_list():
    """列出所有平台的 API Key（快速，不含积分信息）。"""
    try:
        from scanner_integration.config_bridge import get_scan_config
        from scanner_integration.key_manager import KeyManager, init_key_manager
        from scanner_integration.secure_keys import key_id, key_suffix
        init_key_manager()
        km = KeyManager.instance()
        cfg = get_scan_config()
        fofa_email = cfg.get('fofa_email', '')
        result = []
        for platform in ('quake', 'hunter', 'daydaymap', 'fofa'):
            keys = km.get_all_keys(platform)
            for key in keys:
                result.append({
                    'platform': platform,
                    'key_id': key_id(platform, key),
                    'key_suffix': f"...{key_suffix(key)}",
                    'credit': None,
                    'role': '',
                    'role_limit': None,
                    'error': '',
                    'email': fofa_email if platform == 'fofa' else '',
                })
        return jsonify({'ok': True, 'data': result})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@scan_bp.route('/api/scan/keys/credits', methods=['GET'])
def api_scan_keys_credits():
    """查询所有平台的 API Key 积分（慢，调用各平台 API）。"""
    try:
        scanner, err, code = _ensure_scan_bridge()
        if err:
            return err, code
        from scanner_integration.key_manager import (
            KeyManager, init_key_manager,
            check_all_quake_credits,
            check_all_hunter_credits,
            check_all_daydaymap_credits,
            check_all_fofa_credits,
        )
        init_key_manager()
        km = KeyManager.instance()
        from scanner_integration.config_bridge import get_scan_config
        from scanner_integration.secure_keys import key_id, key_suffix
        cfg = get_scan_config()
        fofa_email = cfg.get('fofa_email', '')
        credits_info = {}
        try:
            import asyncio
            async def _fetch_all_credits():
                return await asyncio.gather(
                    check_all_quake_credits(),
                    check_all_hunter_credits(),
                    check_all_daydaymap_credits(),
                    check_all_fofa_credits(),
                    return_exceptions=True,
                )
            quake_r, hunter_r, daydaymap_r, fofa_r = scanner.bridge.run_sync(
                _fetch_all_credits(), timeout=50)
            credits_info['quake'] = quake_r if not isinstance(quake_r, Exception) else []
            credits_info['hunter'] = hunter_r if not isinstance(hunter_r, Exception) else []
            credits_info['daydaymap'] = daydaymap_r if not isinstance(daydaymap_r, Exception) else []
            credits_info['fofa'] = fofa_r if not isinstance(fofa_r, Exception) else []
            for name, val in [('Quake', quake_r), ('Hunter', hunter_r),
                              ('DayDayMap', daydaymap_r), ('Fofa', fofa_r)]:
                if isinstance(val, Exception):
                    logger.warning(f"[Credits] {name} 积分查询失败: {val}")
        except Exception as e:
            logger.warning(f"[Credits] 积分查询失败: {e}")
            for p in ('quake', 'hunter', 'daydaymap', 'fofa'):
                credits_info.setdefault(p, [])
        result = []
        for platform in ('quake', 'hunter', 'daydaymap', 'fofa'):
            keys = km.get_all_keys(platform)
            platform_credits = credits_info.get(platform, [])
            for index, key in enumerate(keys):
                ci = platform_credits[index] if index < len(platform_credits) else {}
                result.append({
                    'platform': platform,
                    'key_id': key_id(platform, key),
                    'key_suffix': f"...{key_suffix(key)}",
                    'credit': _finite_number_or_none(ci.get('credit')),
                    'role': ci.get('role', ''),
                    'role_limit': _finite_number_or_none(ci.get('role_limit')),
                    'error': _redact_value(ci.get('error', ''), key),
                    'email': fofa_email if platform == 'fofa' else '',
                })
        return jsonify({'ok': True, 'data': result})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@scan_bp.route('/api/scan/keys', methods=['POST'])
def api_scan_keys_add():
    """添加一个 API Key。"""
    try:
        from scanner_integration.config_bridge import get_scan_config, save_scan_config
        from scanner_integration.key_manager import init_key_manager
        data = request.get_json(silent=True) or {}
        platform = data.get('platform', '').strip()
        key = data.get('key', '').strip()
        if not platform or not key:
            return jsonify({'ok': False, 'error': '平台和 Key 不能为空'}), 400
        if platform not in SUPPORTED_KEY_PLATFORMS:
            return jsonify({'ok': False, 'error': '不支持的平台'}), 400

        cfg = get_scan_config()
        keys_list = cfg.get(f'{platform}_api_keys', [])
        if not isinstance(keys_list, list):
            keys_list = []
        if key in keys_list:
            return jsonify({'ok': False, 'error': 'Key 已存在'}), 400
        keys_list.append(key)
        cfg[f'{platform}_api_keys'] = keys_list

        # Fofa 需要同步 email
        if platform == 'fofa':
            email = data.get('email', '').strip()
            if not email:
                return jsonify({'ok': False, 'error': 'Fofa Email 不能为空'}), 400
            cfg['fofa_email'] = email

        save_scan_config(cfg)
        init_key_manager()
        return jsonify({'ok': True, 'message': f'{platform} Key 已添加'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@scan_bp.route('/api/scan/keys', methods=['DELETE'])
def api_scan_keys_delete():
    """Delete one API key by its opaque key_id."""
    try:
        from scanner_integration.config_bridge import get_scan_config, save_scan_config
        from scanner_integration.key_manager import init_key_manager
        from scanner_integration.secure_keys import find_key_by_id
        data = request.get_json(silent=True) or {}
        platform = data.get('platform', '').strip()
        requested_id = data.get('key_id', '').strip()
        if not platform or not requested_id:
            return jsonify({'ok': False, 'error': '平台和 key_id 不能为空'}), 400
        if platform not in SUPPORTED_KEY_PLATFORMS:
            return jsonify({'ok': False, 'error': '不支持的平台'}), 400

        cfg = get_scan_config()
        keys_list = cfg.get(f'{platform}_api_keys', [])
        if not isinstance(keys_list, list):
            keys_list = []
        match = find_key_by_id(platform, keys_list, requested_id)
        if match is None:
            return jsonify({'ok': False, 'error': 'Key 不存在'}), 404
        index, _ = match
        keys_list.pop(index)
        cfg[f'{platform}_api_keys'] = keys_list
        if len(keys_list) == 1:
            cfg[f'{platform}_api_key'] = keys_list[0]
        elif len(keys_list) == 0:
            cfg[f'{platform}_api_key'] = ''
        save_scan_config(cfg)
        init_key_manager()
        return jsonify({'ok': True, 'message': 'Key 已删除'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@scan_bp.route('/api/scan/keys', methods=['PUT'])
def api_scan_keys_update():
    """Replace one API key selected only by its opaque key_id."""
    try:
        from scanner_integration.config_bridge import get_scan_config, save_scan_config
        from scanner_integration.key_manager import init_key_manager
        from scanner_integration.secure_keys import find_key_by_id
        data = request.get_json(silent=True) or {}
        platform = data.get('platform', '').strip()
        requested_id = data.get('key_id', '').strip()
        new_key = (data.get('new_key') or data.get('key') or '').strip()
        if not platform or not requested_id or not new_key:
            return jsonify({'ok': False, 'error': '参数不完整'}), 400
        if platform not in SUPPORTED_KEY_PLATFORMS:
            return jsonify({'ok': False, 'error': '不支持的平台'}), 400

        cfg = get_scan_config()
        keys_list = cfg.get(f'{platform}_api_keys', [])
        if not isinstance(keys_list, list):
            keys_list = []
        if platform == 'fofa':
            email = data.get('email', '').strip()
            if not email:
                return jsonify({'ok': False, 'error': 'Fofa Email 不能为空'}), 400
            cfg['fofa_email'] = email
        match = find_key_by_id(platform, keys_list, requested_id)
        if match is None:
            return jsonify({'ok': False, 'error': '原 Key 不存在'}), 404
        idx, old_key = match
        if old_key == new_key:
            save_scan_config(cfg)
            init_key_manager()
            return jsonify({'ok': True, 'message': 'Fofa Email 已更新' if platform == 'fofa' else 'Key 未变更'})
        if any(key == new_key for index, key in enumerate(keys_list) if index != idx):
            return jsonify({'ok': False, 'error': '新 Key 已存在'}), 400
        keys_list[idx] = new_key
        cfg[f'{platform}_api_keys'] = keys_list
        if len(keys_list) == 1:
            cfg[f'{platform}_api_key'] = keys_list[0]
        save_scan_config(cfg)
        init_key_manager()
        return jsonify({'ok': True, 'message': 'Key 已更新'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@scan_bp.route('/api/scan/stats', methods=['GET'])
def api_scan_stats():
    """获取扫描结果统计。"""
    scanner = _get_scanner()
    if scanner is None:
        return jsonify({'ok': True, 'data': {'by_category': {}, 'by_province': {}}})
    scan_id = request.args.get('scan_id')
    return jsonify({'ok': True, 'data': scanner.get_scan_stats(scan_id=scan_id)})


@scan_bp.route('/api/scan/yield-stats', methods=['GET'])
def api_scan_yield_stats():
    """Return persisted platform/profile yield stats."""
    scan_id = request.args.get('scan_id')
    limit = int_arg(request.args, 'limit', 200, 1, 1000)
    return jsonify({'ok': True, 'data': db.get_scan_yield_stats(scan_id=scan_id, limit=limit)})


# ─────────────── 持久化扫描结果 API ───────────────

@scan_bp.route('/api/scan/persistent/grouped', methods=['GET'])
def api_persistent_grouped():
    """获取持久化结果按 platform → source_ip 两级分组汇总。"""
    scanner, err, code = _ensure_scan_bridge()
    if err:
        return err, code
    return jsonify({'ok': True, 'data': scanner.get_persistent_grouped()})


@scan_bp.route('/api/scan/persistent/details', methods=['GET'])
def api_persistent_details():
    """获取某个来源 IP 的频道明细。"""
    scanner, err, code = _ensure_scan_bridge()
    if err:
        return err, code
    source_ip = request.args.get('source_ip', '')
    if not source_ip:
        return jsonify({'ok': False, 'error': 'source_ip is required'}), 400
    page = int_arg(request.args, 'page', 1, 1, None)
    size = int_arg(request.args, 'size', 50, 1, 200)
    search = request.args.get('search', '').strip()
    quality = request.args.get('quality', '').strip()
    category = request.args.get('category', '').strip()
    province = request.args.get('province', '').strip()
    return jsonify({'ok': True, 'data': scanner.get_persistent_details(
        source_ip,
        page=page,
        size=size,
        search=search,
        quality=quality,
        category=category,
        province=province,
    )})


@scan_bp.route('/api/scan/persistent/stats', methods=['GET'])
def api_persistent_stats():
    """获取持久化结果的质量分布统计。"""
    scanner, err, code = _ensure_scan_bridge()
    if err:
        return err, code
    return jsonify({'ok': True, 'data': scanner.get_persistent_stats()})


@scan_bp.route('/api/scan/persistent/manual-check', methods=['POST'])
def api_persistent_manual_check():
    """手动触发一轮持久化结果检测。"""
    scanner, err, code = _ensure_scan_bridge()
    if err:
        return err, code
    return jsonify({'ok': True, 'data': scanner.trigger_persistent_manual_check()})


@scan_bp.route('/api/scan/persistent/<int:row_id>', methods=['DELETE'])
def api_persistent_delete(row_id):
    """删除单条持久化结果。"""
    scanner, err, code = _ensure_scan_bridge()
    if err:
        return err, code
    return jsonify({'ok': True, 'data': scanner.delete_persistent_item(row_id)})


# ─────────────── 检测记录 API ───────────────

@scan_bp.route('/api/scan/detection/logs', methods=['GET'])
def api_detection_logs():
    """获取定期检测日志。"""
    from database import get_detection_logs
    limit = int_arg(request.args, 'limit', 200, 1, 1000)
    return jsonify({'ok': True, 'data': get_detection_logs(limit=limit)})


@scan_bp.route('/api/scan/detection/status', methods=['GET'])
def api_detection_status():
    """Return the live detection scheduler status."""
    scanner, err, code = _ensure_scan_bridge()
    if err:
        return err, code
    return jsonify({'ok': True, 'data': scanner.get_detection_status()})


@scan_bp.route('/api/scan/detection/runs', methods=['GET'])
def api_detection_runs():
    """获取检测轮次记录，支持 start/end 时间范围过滤。"""
    start = request.args.get('start')
    end = request.args.get('end')
    limit = int_arg(request.args, 'limit', 100, 1, 500)
    scanner, err, code = _ensure_scan_bridge()
    if err:
        return err, code
    return jsonify({'ok': True, 'data': scanner.get_detection_runs(start, end, limit)})


@scan_bp.route('/api/scan/detection/run/<cycle_id>/results', methods=['GET'])
def api_detection_run_results(cycle_id):
    """获取某轮检测的所有 URL 结果明细。"""
    scanner, err, code = _ensure_scan_bridge()
    if err:
        return err, code
    page = int_arg(request.args, 'page', 1, 1, None)
    size = int_arg(request.args, 'size', 100, 1, 200)
    search = (request.args.get('search') or '').strip()[:200]
    outcome = (request.args.get('outcome') or '').strip().lower()
    quality = (request.args.get('quality') or '').strip()[:50]
    sort_by = (request.args.get('sort_by') or '').strip()
    sort_order = (request.args.get('sort_order') or 'asc').strip().lower()
    return jsonify({'ok': True, 'data': scanner.get_detection_results(
        cycle_id,
        page=page,
        size=size,
        search=search,
        outcome=outcome,
        quality=quality,
        sort_by=sort_by,
        sort_order=sort_order,
    )})


@scan_bp.route('/api/scan/persistent/recheck', methods=['POST'])
def api_persistent_recheck():
    """重新检测指定频道。"""
    import database as db

    data = request.get_json(silent=True) or {}
    url = data.get('url')
    if not url:
        return jsonify({'ok': False, 'error': 'url is required'}), 400

    ok, reason = _validate_recheck_url(url)
    if not ok:
        return jsonify({'ok': False, 'error': reason}), 400

    async def _do_recheck():
        started = time.monotonic()
        response = await safe_fetch(
            url,
            timeout=20,
            max_bytes=DEFAULT_MAX_RESPONSE_BYTES,
            allow_rfc1918=False,
        )
        elapsed = max(time.monotonic() - started, 0.001)
        if 200 <= response.status < 300 and response.body:
            delay = round(elapsed * 1000, 1)
            bandwidth = round(len(response.body) / elapsed / (1024 * 1024), 4)
            stability = 100
            db.update_persistent_check(
                url, ok=True, stability=stability,
                delay=delay, bandwidth=bandwidth, jitter=0,
            )
            return {
                'ok': True,
                'stability': stability,
                'delay': delay,
                'bandwidth': bandwidth,
                'http_status': response.status,
            }
        db.update_persistent_check(url, ok=False)
        return {'ok': False, 'reason': f'HTTP {response.status}'}

    try:
        scanner, err, code = _ensure_scan_bridge()
        if err:
            return err, code
        result = scanner.bridge.run_sync(_do_recheck(), timeout=30)
        return jsonify({'ok': True, 'data': result})
    except scanner.BridgeTimeoutError as e:
        return jsonify({'ok': False, 'error': str(e)}), 504
    except asyncio.TimeoutError:
        return jsonify({'ok': False, 'error': '远端检测超时'}), 504
    except NetworkPolicyError as e:
        return jsonify({'ok': False, 'error': str(e)}), 422
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@scan_bp.route('/api/scan/persistent/priority', methods=['POST'])
def api_persistent_priority():
    """更新频道优先级。"""
    import database as db

    data = request.get_json(silent=True) or {}
    url = data.get('url')
    if not url:
        return jsonify({'ok': False, 'error': 'url is required'}), 400
    try:
        priority = int(data.get('priority', 0))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'priority must be 0, 1, or 2'}), 400
    if priority not in (0, 1, 2):
        return jsonify({'ok': False, 'error': 'priority must be 0, 1, or 2'}), 400

    try:
        conn = db._get_conn()
        conn.execute(
            "UPDATE persistent_scan_results SET priority = %s WHERE url = %s",
            (priority, url)
        )
        conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@scan_bp.route('/api/detection/stream')
def api_detection_stream():
    """SSE 实时推送检测日志。"""
    scanner = _get_scanner()
    if scanner is None:
        return jsonify({'ok': False, 'error': '扫描模块未安装'}), 503
    slot = acquire_sse_slot()
    if slot is None:
        return jsonify({'ok': False, 'error': 'SSE 连接数已达上限'}), 429

    def generate():
        import json
        q = None
        deadline = time.monotonic() + SSE_MAX_DURATION_SECONDS
        try:
            q = scanner.subscribe_detection_sse()
            try:
                status = scanner.get_detection_status()
                yield f"event: status\ndata: {json.dumps(status, ensure_ascii=False)}\n\n"
            except Exception:
                pass
            from database import get_detection_logs
            recent = get_detection_logs(limit=50)
            if recent:
                for entry in recent:
                    yield f"event: log\ndata: {json.dumps(entry, ensure_ascii=False)}\n\n"
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    yield f"event: error\ndata: {json.dumps({'error': 'SSE 连接超时，请重新连接'})}\n\n"
                    break
                try:
                    msg = q.get(timeout=min(30, remaining))
                    yield msg
                except Exception:
                    yield ": heartbeat\n\n"
        except GeneratorExit:
            pass
        finally:
            if q is not None:
                scanner.unsubscribe_detection_sse(q)
            slot.release()

    response = Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        }
    )
    response.call_on_close(slot.release)
    return response

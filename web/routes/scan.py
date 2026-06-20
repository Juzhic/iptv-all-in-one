# -*- coding: utf-8 -*-
"""web 包 — 扫描模块 API 蓝图。"""
import logging
from flask import Blueprint, request, jsonify

import database as db
import web.state as _state
from web.app import _finite_number_or_none

logger = logging.getLogger(__name__)

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
    return jsonify({'ok': True, 'message': '扫描已启动'})


@scan_bp.route('/api/scan/stop', methods=['POST'])
def api_scan_stop():
    """请求停止扫描。"""
    scanner, err, code = _ensure_scan_bridge()
    if err:
        return err, code
    result = scanner.trigger_stop()
    return jsonify({'ok': True, 'data': result})


@scan_bp.route('/api/scan/force-clear', methods=['POST'])
def api_scan_force_clear():
    """强制清除卡死的扫描状态。"""
    scanner = _get_scanner()
    if scanner is None:
        db.clear_scan_progress()
        return jsonify({'ok': True, 'message': '扫描状态已清除'})
    result = scanner.force_clear_scan()
    return jsonify({'ok': True, 'data': result})


@scan_bp.route('/api/scan/status', methods=['GET'])
def api_scan_status():
    """获取扫描实时进度。"""
    scanner = _get_scanner()
    if scanner is None:
        return jsonify({'ok': True, 'data': {'running': False, 'phase': 'idle', 'message': '扫描模块未安装'}})
    status = scanner.get_scan_status()
    return jsonify({'ok': True, 'data': status})


@scan_bp.route('/api/scan/results', methods=['GET'])
def api_scan_results():
    """分页查询扫描结果。"""
    scanner = _get_scanner()
    if scanner is None:
        return jsonify({'ok': True, 'items': [], 'total': 0})
    scan_id = request.args.get('scan_id')
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 50, type=int)
    size = min(size, 200)
    category = request.args.get('category')
    province = request.args.get('province')
    search = request.args.get('search')
    total, items = scanner.get_scan_results(
        scan_id=scan_id, page=page, size=size,
        category=category, province=province, search=search
    )
    return jsonify({'ok': True, 'items': items, 'total': total, 'page': page, 'size': size})


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
    limit = request.args.get('limit', 50, type=int)
    items = scanner.get_scan_history(limit=limit)
    return jsonify({'ok': True, 'items': items, 'total': len(items)})


@scan_bp.route('/api/scan/config', methods=['GET'])
def api_scan_config_get():
    """读取扫描配置。"""
    try:
        from scanner_integration.config_bridge import get_scan_config
        cfg = get_scan_config()
        return jsonify({'ok': True, 'data': cfg})
    except Exception:
        from scanner_integration.config_bridge import DEFAULT_SCAN_CONFIG
        return jsonify({'ok': True, 'data': DEFAULT_SCAN_CONFIG})


@scan_bp.route('/api/scan/config', methods=['POST'])
def api_scan_config_set():
    """保存扫描配置。"""
    try:
        from scanner_integration.config_bridge import save_scan_config, get_scan_config
        from scanner_integration.key_manager import init_key_manager
        data = request.get_json(silent=True) or {}
        save_scan_config(data)
        init_key_manager()
        cfg = get_scan_config()
        return jsonify({'ok': True, 'data': cfg})
    except Exception as e:
        return jsonify({'ok': False, 'error': f'保存失败: {e}'}), 500


@scan_bp.route('/api/scan/keys', methods=['GET'])
def api_scan_keys_list():
    """列出所有平台的 API Key（含积分信息）。"""
    try:
        from scanner_integration.key_manager import KeyManager, init_key_manager
        from scanner_integration.config_bridge import get_scan_config
        init_key_manager()
        km = KeyManager.instance()
        cfg = get_scan_config()
        credits_info = {}
        try:
            import asyncio
            from scanner_integration.key_manager import check_all_quake_credits
            credits_info['quake'] = asyncio.run(check_all_quake_credits())
        except Exception as e:
            logger.warning(f"[Credits] Quake 积分查询失败: {e}")
            credits_info['quake'] = []
        try:
            import asyncio
            from scanner_integration.key_manager import check_all_hunter_credits
            credits_info['hunter'] = asyncio.run(check_all_hunter_credits())
        except Exception as e:
            logger.warning(f"[Credits] Hunter 积分查询失败: {e}")
            credits_info['hunter'] = []
        try:
            import asyncio
            from scanner_integration.key_manager import check_all_daydaymap_credits
            credits_info['daydaymap'] = asyncio.run(check_all_daydaymap_credits())
        except Exception as e:
            logger.warning(f"[Credits] DayDayMap 积分查询失败: {e}")
            credits_info['daydaymap'] = []
        logger.info(f"[Credits] results: hunter={credits_info.get('hunter')}, daydaymap={credits_info.get('daydaymap')}")
        result = []
        for platform in ('quake', 'hunter', 'daydaymap'):
            keys = km.get_all_keys(platform)
            platform_credits = credits_info.get(platform, [])
            credit_map = {c['key_suffix']: c for c in platform_credits}
            for key in keys:
                suffix = f"...{key[-6:]}"
                ci = credit_map.get(suffix, {})
                result.append({
                    'platform': platform,
                    'key': key,
                    'key_suffix': suffix,
                    'credit': _finite_number_or_none(ci.get('credit')),
                    'role': ci.get('role', ''),
                    'role_limit': _finite_number_or_none(ci.get('role_limit')),
                    'error': ci.get('error', ''),
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
        if platform not in ('quake', 'hunter', 'daydaymap'):
            return jsonify({'ok': False, 'error': '不支持的平台'}), 400

        cfg = get_scan_config()
        keys_list = cfg.get(f'{platform}_api_keys', [])
        if not isinstance(keys_list, list):
            keys_list = []
        if key in keys_list:
            return jsonify({'ok': False, 'error': 'Key 已存在'}), 400
        keys_list.append(key)
        cfg[f'{platform}_api_keys'] = keys_list
        save_scan_config(cfg)
        init_key_manager()
        return jsonify({'ok': True, 'message': f'{platform} Key 已添加'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@scan_bp.route('/api/scan/keys', methods=['DELETE'])
def api_scan_keys_delete():
    """删除一个 API Key。"""
    try:
        from scanner_integration.config_bridge import get_scan_config, save_scan_config
        from scanner_integration.key_manager import init_key_manager
        data = request.get_json(silent=True) or {}
        platform = data.get('platform', '').strip()
        key = data.get('key', '').strip()
        if not platform or not key:
            return jsonify({'ok': False, 'error': '平台和 Key 不能为空'}), 400

        cfg = get_scan_config()
        keys_list = cfg.get(f'{platform}_api_keys', [])
        if not isinstance(keys_list, list):
            keys_list = []
        if key in keys_list:
            keys_list.remove(key)
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
    """更新一个 API Key（替换旧值）。"""
    try:
        from scanner_integration.config_bridge import get_scan_config, save_scan_config
        from scanner_integration.key_manager import init_key_manager
        data = request.get_json(silent=True) or {}
        platform = data.get('platform', '').strip()
        old_key = data.get('old_key', '').strip()
        new_key = data.get('new_key', '').strip()
        if not platform or not old_key or not new_key:
            return jsonify({'ok': False, 'error': '参数不完整'}), 400
        if old_key == new_key:
            return jsonify({'ok': True, 'message': 'Key 未变更'})

        cfg = get_scan_config()
        keys_list = cfg.get(f'{platform}_api_keys', [])
        if not isinstance(keys_list, list):
            keys_list = []
        if old_key not in keys_list:
            return jsonify({'ok': False, 'error': '原 Key 不存在'}), 400
        if new_key in keys_list:
            return jsonify({'ok': False, 'error': '新 Key 已存在'}), 400
        idx = keys_list.index(old_key)
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
    page = request.args.get('page', type=int)
    size = request.args.get('size', 50, type=int)
    size = min(size, 200)
    return jsonify({'ok': True, 'data': scanner.get_persistent_details(source_ip, page=page, size=size)})


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
    limit = request.args.get('limit', 200, type=int)
    return jsonify({'ok': True, 'data': get_detection_logs(limit=limit)})


@scan_bp.route('/api/scan/detection/runs', methods=['GET'])
def api_detection_runs():
    """获取检测轮次记录，支持 start/end 时间范围过滤。"""
    start = request.args.get('start')
    end = request.args.get('end')
    limit = request.args.get('limit', 100, type=int)
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
    page = request.args.get('page', type=int)
    size = request.args.get('size', 100, type=int)
    size = min(size, 200)
    return jsonify({'ok': True, 'data': scanner.get_detection_results(cycle_id, page=page, size=size)})


@scan_bp.route('/api/scan/persistent/recheck', methods=['POST'])
def api_persistent_recheck():
    """重新检测指定频道。"""
    import database as db
    from scanner_integration.video_check import deep_check
    from scanner_integration.network import get_session
    import asyncio

    data = request.get_json(silent=True) or {}
    url = data.get('url')
    if not url:
        return jsonify({'ok': False, 'error': 'url is required'}), 400

    async def _do_recheck():
        async with get_session(limit=5, timeout=10) as session:
            result = await deep_check(session, url)
            if result:
                db.update_persistent_check(
                    url, ok=True,
                    stability=result.get('stability'),
                    delay=result.get('delay'),
                    bandwidth=result.get('bandwidth'),
                    jitter=result.get('jitter'),
                )
                return {'ok': True, 'stability': result.get('stability'), 'delay': result.get('delay')}
            else:
                db.update_persistent_check(url, ok=False)
                return {'ok': False, 'reason': 'deep_check failed'}

    try:
        scanner, err, code = _ensure_scan_bridge()
        if err:
            return err, code
        result = scanner.bridge.run_sync(_do_recheck(), timeout=30)
        return jsonify({'ok': True, 'data': result})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@scan_bp.route('/api/scan/persistent/priority', methods=['POST'])
def api_persistent_priority():
    """更新频道优先级。"""
    import database as db

    data = request.get_json(silent=True) or {}
    url = data.get('url')
    priority = data.get('priority', 0)
    if not url:
        return jsonify({'ok': False, 'error': 'url is required'}), 400
    if priority not in (0, 1, 2):
        return jsonify({'ok': False, 'error': 'priority must be 0, 1, or 2'}), 400

    try:
        conn = db._get_conn()
        conn.execute(
            "UPDATE persistent_scan_results SET priority = ? WHERE url = ?",
            (priority, url)
        )
        conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

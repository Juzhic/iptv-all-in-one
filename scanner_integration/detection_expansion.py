"""Bounded discovery from freshly checked pool sources; no search API calls."""
import asyncio
import ipaddress
import json
import time
import uuid
from urllib.parse import urlsplit

from . import config_bridge
from .network import get_session
from .platforms.ip_extract import _pick_c_segment_ips, extract_channels_from_ip
from .video_check import deep_filter_batch, filter_hd, quality_gate_failure

COOLDOWN_KEY = 'detection_expansion_cooldowns'


def public_http_endpoint(url):
    try:
        parsed = urlsplit(url)
        ip = ipaddress.ip_address(parsed.hostname)
        port = parsed.port or 80
        if (parsed.scheme == 'http' and not parsed.username and not parsed.password
                and ip.version == 4 and ip.is_global and not ip.is_multicast
                and 0 < port < 65536):
            return str(ip), port
    except (ValueError, TypeError):
        pass
    return None


def plan_expansion(seeds, cfg, cooldowns, now):
    thresholds = config_bridge.get_quality_thresholds(cfg)
    groups = {}
    for seed in sorted(seeds, key=lambda s: -(s.get('stability') or 0)):
        endpoint = public_http_endpoint(seed.get('url', ''))
        if not endpoint or quality_gate_failure(seed, thresholds):
            continue
        ip, port = endpoint
        segment = str(ipaddress.ip_network(f'{ip}/24', strict=False))
        key = f'{segment}:{port}'
        if now - cooldowns.get(key, 0) < cfg['detection_expansion_cooldown_hours'] * 3600:
            continue
        groups.setdefault(key, seed)
    chosen = list(groups.items())[:cfg['detection_expansion_max_segments']]
    if not chosen:
        return []
    base, extra = divmod(cfg['detection_expansion_max_ips'], len(chosen))
    known_endpoints = {public_http_endpoint(seed.get('url', '')) for seed in seeds}
    plans = []
    for index, (key, seed) in enumerate(chosen):
        ip, port = public_http_endpoint(seed['url'])
        limit = base + (index < extra)
        if limit:
            neighbors = [neighbor for neighbor in _pick_c_segment_ips(ip, 254)
                         if (neighbor, port) not in known_endpoints]
            # Near neighbors first; avoid repeatedly spending the budget on distant IPs.
            neighbors.sort(key=lambda value: abs(int(value.rsplit('.', 1)[1]) - int(ip.rsplit('.', 1)[1])))
            plans.append((key, seed, [(neighbor, port) for neighbor in neighbors[:limit]]))
    return plans


async def expand_after_detection(seeds, cfg, log_fn):
    import database as db
    result = {'probed_ips': 0, 'discovered': 0, 'added': 0, 'segments': 0}
    if not cfg.get('enable_c_scan') or not cfg.get('detection_expansion_enabled') or not seeds:
        return result
    task_id = uuid.uuid4().hex
    acquired, _ = db.acquire_task_lease('detection_expansion', task_id, 'detection',
                                       lease_seconds=180, message='复检后 C 段拓展')
    if not acquired:
        log_fn('INFO', '[复检拓展] 另一轮拓展正在运行，本轮跳过')
        return result
    state = 'completed'
    try:
        now = time.time()
        stored = json.loads(db.get_config_data(COOLDOWN_KEY) or '{}')
        if not isinstance(stored, dict):
            raise ValueError('拓展冷却记录格式异常')
        cooldowns = {key: value for key, value in stored.items()
                     if isinstance(value, (int, float)) and 0 <= now - value < 720 * 3600}
        plans = plan_expansion(seeds, cfg, cooldowns, now)
        if not plans:
            log_fn('INFO', '[复检拓展] 无符合条件的新网段，或网段仍在冷却期')
            return result
        known = {row['url'] for row in db.get_all_persistent_for_check()}
        thresholds = config_bridge.get_quality_thresholds(cfg)
        remaining = cfg['detection_expansion_max_channels']
        log_fn('INFO', f'[复检拓展] 开始：{len(plans)} 个网段/端口，最多 {cfg["detection_expansion_max_ips"]} 个 IP，最多检测 {remaining} 条新频道')
        try:
            async with asyncio.timeout(120), get_session(limit=5, timeout=5, force_close=True) as session:
                for key, seed, endpoints in plans:
                    if remaining <= 0:
                        break
                    # Persist before probing so failed/cancelled runs also cool down.
                    cooldowns[key] = time.time()
                    cooldowns = dict(sorted(cooldowns.items(), key=lambda item: item[1])[-2048:])
                    db.set_config_data(COOLDOWN_KEY, json.dumps(cooldowns))
                    result['segments'] += 1
                    for start in range(0, len(endpoints), 5):
                        if remaining <= 0:
                            break
                        batch = endpoints[start:start + 5]
                        result['probed_ips'] += len(batch)
                        responses = await asyncio.gather(*[
                            extract_channels_from_ip(ip, port, session, seed.get('province', ''),
                                                     seed.get('city', ''), timeout=2, include_fallback_ports=False)
                            for ip, port in batch
                        ], return_exceptions=True)
                        candidates = []
                        for endpoint, channels in zip(batch, responses):
                            if not isinstance(channels, list):
                                continue
                            for channel in channels:
                                url = channel.get('url', '')
                                if (remaining <= 0 or url in known
                                        or public_http_endpoint(url) != endpoint):
                                    continue
                                known.add(url)
                                remaining -= 1
                                candidates.append({**channel, 'platform': seed.get('platform') or '复检C段拓展'})
                        result['discovered'] += len(candidates)
                        checked = await deep_filter_batch(candidates, asyncio.Semaphore(5), session)
                        accepted = [ch for ch in filter_hd(checked) if quality_gate_failure(ch, thresholds) is None]
                        if accepted:
                            db.upsert_persistent_results(accepted)
                            db.batch_update_persistent_checks([{**ch, 'ok': True} for ch in accepted])
                            result['added'] += len(accepted)
        except asyncio.TimeoutError:
            result['timed_out'] = True
            log_fn('INFO', '[复检拓展] 达到 120 秒时间上限，保留已完成结果')
        log_fn('INFO', f'[复检拓展] 完成：探测 {result["probed_ips"]} 个 IP，发现 {result["discovered"]} 条新候选，质量通过入池 {result["added"]} 条')
        return result
    except asyncio.CancelledError:
        state = 'cancelled'
        raise
    except Exception:
        state = 'failed'
        raise
    finally:
        db.finish_task_lease('detection_expansion', task_id, state=state, message='复检拓展结束')

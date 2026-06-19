"""Channel auto-discovery from subscription sources."""
import re
import logging
from engine.test_engine import load_subscribe_urls, fetch_m3u_playlist, parse_iptv_addresses, parse_demo_file
from engine.alias import load_aliases, match_channel_name, strip_quality_suffix

logger = logging.getLogger('iptv_discovery')

_EMOJI_RE = re.compile(
    "["
    "\U0001f300-\U0001f9ff"
    "\U00002702-\U000027b0"
    "\U0000fe00-\U0000fe0f"
    "\U0000200d"
    "\U00002600-\U000026ff"
    "\U0000231a-\U0000231b"
    "\U00002b50"
    "\U000023f0-\U000023fa"
    "]+",
    flags=re.UNICODE,
)


def _strip_emoji(text):
    return _EMOJI_RE.sub("", text).strip()


def discover_channels():
    """Scan all subscription sources and discover available channels.

    Returns:
        dict: {
            'categories': {category_name: [{'name': ch_name, 'count': source_count, 'in_template': bool}]},
            'total_discovered': int,
            'total_in_template': int,
            'total_new': int,
        }
    """
    _, name_to_canonical, regex_aliases = load_aliases()

    # Build template channel set
    demo_structure = parse_demo_file()
    template_channels = set()
    for _, channels in demo_structure:
        for ch in channels:
            template_channels.add(ch)

    # Fetch and parse all M3U sources
    urls = load_subscribe_urls()
    all_channels = {}  # {canonical_name: {'count': int, 'raw_names': set}}

    for url in urls:
        try:
            content = fetch_m3u_playlist(url)
            if not content:
                continue
            parsed = parse_iptv_addresses(content)
            for ch_info, stream_url in parsed:
                raw_name = ch_info.get('name', '').strip()
                if not raw_name:
                    continue

                # Try alias match first
                canonical = match_channel_name(raw_name, name_to_canonical, regex_aliases)
                if not canonical:
                    stripped = strip_quality_suffix(raw_name)
                    canonical = match_channel_name(stripped, name_to_canonical, regex_aliases)
                    if not canonical:
                        canonical = stripped

                if canonical not in all_channels:
                    all_channels[canonical] = {'count': 0, 'raw_names': set()}
                all_channels[canonical]['count'] += 1
                all_channels[canonical]['raw_names'].add(raw_name)
        except Exception as e:
            logger.debug(f"[Discovery] 跳过源 {url}: {e}")

    # Classify channels
    try:
        from scanner_integration.channel_utils import auto_classify, is_blacklisted
    except ImportError:
        auto_classify = None
        is_blacklisted = lambda n: False

    categories = {}
    for ch_name, info in all_channels.items():
        if is_blacklisted(ch_name):
            continue

        if auto_classify:
            category, _ = auto_classify(ch_name)
        else:
            category = '其他频道'

        if category not in categories:
            categories[category] = []
        categories[category].append({
            'name': ch_name,
            'count': info['count'],
            'in_template': ch_name in template_channels,
        })

    # Sort within each category: in_template first, then by count desc
    for cat in categories:
        categories[cat].sort(key=lambda x: (not x['in_template'], -x['count']))

    total = sum(len(chs) for chs in categories.values())
    in_tmpl = sum(1 for chs in categories.values() for ch in chs if ch['in_template'])

    return {
        'categories': categories,
        'total_discovered': total,
        'total_in_template': in_tmpl,
        'total_new': total - in_tmpl,
    }


def merge_channels_into_demo(channels_to_add):
    """Merge discovered channels into the demo template.

    Args:
        channels_to_add: list of {'name': str, 'category': str}

    Returns:
        dict with 'added_count', 'skipped_count', 'new_genres'
    """
    from database import get_config_data, set_config_data

    demo_content = get_config_data('demo')
    demo_structure = parse_demo_file()

    # Build lookup: genre -> (ordered list, set for dedup)
    # Also build a normalized genre name map for matching (strip emojis)
    genre_channels = {}
    genre_order = []
    genre_normalized = {}  # normalized_name -> actual_genre
    for genre, channels in demo_structure:
        genre_channels[genre] = {'list': list(channels), 'set': set(channels)}
        genre_order.append(genre)
        genre_normalized[_strip_emoji(genre)] = genre

    added = 0
    skipped = 0
    new_genres = []

    for item in channels_to_add:
        name = item.get('name', '').strip()
        category = item.get('category', '').strip()
        if not name or not category:
            continue

        # Find existing genre (try exact match first, then normalized match)
        target_genre = None
        for genre in genre_order:
            if genre == category:
                target_genre = genre
                break
        if target_genre is None:
            normalized = _strip_emoji(category)
            if normalized in genre_normalized:
                target_genre = genre_normalized[normalized]

        if target_genre is None:
            target_genre = category
            genre_channels[target_genre] = {'list': [], 'set': set()}
            genre_order.append(target_genre)
            new_genres.append(target_genre)

        if name in genre_channels[target_genre]['set']:
            skipped += 1
            continue

        genre_channels[target_genre]['list'].append(name)
        genre_channels[target_genre]['set'].add(name)
        added += 1

    # Rebuild demo content preserving original order
    lines = []
    for genre in genre_order:
        data = genre_channels[genre]
        if not data['list']:
            continue
        lines.append(f'{genre},#genre#')
        for ch in data['list']:
            lines.append(ch)
        lines.append('')

    set_config_data('demo', '\n'.join(lines))

    return {
        'added_count': added,
        'skipped_count': skipped,
        'new_genres': new_genres,
    }

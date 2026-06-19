# geo_data.py
import re
import os
import json
from .province_cities import PROVINCES, PROVINCE_CITIES, PROVINCE_CHANNEL_PATTERNS
from .logger_bridge import logger

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))

CITY_TO_PROVINCE = {}
for prov, cities in PROVINCE_CITIES.items():
    for city in cities:
        clean = re.sub(r'[市区州]', '', city)
        if clean:
            CITY_TO_PROVINCE[clean] = prov

try:
    from .province_cities import DISTRICT_CITIES
    CITY_TO_PROVINCE.update(DISTRICT_CITIES)
except Exception:
    pass

def normalize_province(prov):
    if not prov:
        return prov
    full = {
        '广西壮族自治区': '广西', '内蒙古自治区': '内蒙古', '西藏自治区': '西藏',
        '宁夏回族自治区': '宁夏', '新疆维吾尔自治区': '新疆',
        '香港特别行政区': '香港', '澳门特别行政区': '澳门'
    }
    return full.get(prov, re.sub(r'[省市自治区]$', '', prov))

def load_local_districts():
    pca_path = os.path.join(_PKG_DIR, "pca-code.json")
    if not os.path.exists(pca_path):
        logger.warning("本地 pca-code.json 未找到，仅使用内置区县映射")
        return {}
    try:
        with open(pca_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        district_map = {}
        for prov_item in data:
            prov_name = prov_item.get("name", "")
            prov_short = normalize_province(prov_name)
            if not prov_short:
                continue
            for city_item in prov_item.get("children", []):
                districts = city_item.get("children", [])
                if districts:
                    for dist_item in districts:
                        dist_name = dist_item.get("name", "")
                        if dist_name:
                            # 同时存储原始名和去除“区县市”尾缀的干净名
                            clean = re.sub(r'[区县市]$', '', dist_name)
                            district_map[dist_name] = prov_short
                            if clean != dist_name:
                                district_map[clean] = prov_short
                else:
                    city_name = city_item.get("name", "")
                    if city_name:
                        clean = re.sub(r'[区县市]$', '', city_name)
                        district_map[city_name] = prov_short
                        if clean != city_name:
                            district_map[clean] = prov_short
        logger.info(f"从本地 pca-code.json 加载区县映射 {len(district_map)} 条")
        return district_map
    except Exception as e:
        logger.warning(f"本地 pca-code.json 解析失败: {e}")
        return {}

def extract_province_from_name(name):
    if not name:
        return None
    name_upper = name.upper()
    # 1. 关键字匹配
    for prov, data in PROVINCE_CHANNEL_PATTERNS.items():
        for kw in data['keywords']:
            if kw in name:
                return prov
            if kw.isascii() and kw.upper() in name_upper:
                return prov
        for p in data.get('patterns', []):
            if re.search(p, name):
                return prov
    # 2. 城市/区县匹配（已包含 pca-code.json 的清理后映射）
    for city, prov in CITY_TO_PROVINCE.items():
        if len(city) >= 2 and city in name:
            return prov
    return None

def is_channel_match_province(name, province, strict=False):
    if not name or not province or province not in PROVINCE_CHANNEL_PATTERNS:
        return False
    data = PROVINCE_CHANNEL_PATTERNS[province]
    if strict:
        name_upper = name.upper()
        for kw in data['keywords']:
            if kw in name or (kw.isascii() and kw.upper() in name_upper):
                return True
        for p in data.get('patterns', []):
            if re.search(p, name):
                return True
        return False
    return any(kw in name for kw in data['keywords'])

def is_channel_match_city(name, city, province=None):
    if not name or not city:
        return False
    return city in name or (province and province in PROVINCE_CHANNEL_PATTERNS
                            and city in PROVINCE_CHANNEL_PATTERNS[province]['keywords'])
import math


def safe_number(value, default=None):
    """将值安全转换为有限数字，无效返回default"""
    try:
        num = float(value)
        return num if math.isfinite(num) else default
    except (TypeError, ValueError):
        return default

# -*- coding: utf-8 -*-
"""Small helpers for normalizing route parameters."""


def bounded_int(value, default, min_value=None, max_value=None):
    """Return an int constrained to an optional range."""
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = default
    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value


def int_arg(args, name, default, min_value=None, max_value=None):
    """Read an integer query parameter with sane fallback and bounds."""
    return bounded_int(args.get(name, default), default, min_value, max_value)

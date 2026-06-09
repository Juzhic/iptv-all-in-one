# -*- coding: utf-8 -*-
import logging
import sys

logger = logging.getLogger('iptv_scan')
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', '%H:%M:%S'))
    logger.addHandler(_handler)
    logger.propagate = False

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os

def configure_logging(config_file):
    from logging.config import dictConfig
    import yaml
    with open(os.path.join(os.path.dirname(__file__), config_file), 'r') as f:
        config = yaml.safe_load(f.read())
        dictConfig(config)

def get_logger(name):
    from logging import getLogger
    return getLogger(name)

import json

DEFAULTS = {
    'retries': 3,
    'timeout': 30,
}

def load():
    cfg = dict(DEFAULTS)
    return cfg

def path_for(name):
    return '/etc/demo/' + name


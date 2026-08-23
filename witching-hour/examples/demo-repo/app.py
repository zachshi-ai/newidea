import config
import threading

cache = {}
cache_lock = threading.Lock()
running = True

def handle(event):
    with cache_lock:
        if event.kind in cache:
            return cache[event.kind]
        cache[event.kind] = process(event)
        return cache[event.kind]

def process(event):
    cfg = config.load()
    return cfg.get(event.kind, None)

def main():
    while running:
        handle(next_event())


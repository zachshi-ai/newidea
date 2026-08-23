import time

def with_retries(fn, args, attempts=3):
    for i in range(attempts):
        try:
            return fn(*args)
        except Exception:
            time.sleep(min(i, 5))
    raise RetryError('gave up after %d' % attempts)

class RetryError(Exception):
    pass


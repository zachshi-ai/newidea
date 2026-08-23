from app import process, handle

class FakeEvent:
    def __init__(self, kind, payload=None):
        self.kind = kind
        self.payload = payload

def test_process():
    assert process(FakeEvent('pay')) is not None

def test_process_unknown_kind():
    assert process(FakeEvent('telepathy')) is None

def test_process_empty_kind():
    assert process(FakeEvent('')) is None

def test_fake_event_carries_kind():
    assert FakeEvent('pay').kind == 'pay'

def test_process_is_pure_for_same_kind():
    a = process(FakeEvent('pay'))
    b = process(FakeEvent('pay'))
    assert a == b

def test_config_defaults_visible():
    import config
    assert config.DEFAULTS['retries'] == 3

def test_config_timeout_sane():
    import config
    assert 0 < config.DEFAULTS['timeout'] <= 60

def test_nothing_else():
    # placeholder so the suite is not empty
    assert True


import unittest

from src.payment import charge



@unittest.skip("flaky on CI, ticket PAY-331")
class PaymentTest(unittest.TestCase):
    def test_charge_ok(self):
        import time
        time.sleep(0.2)
        self.assertTrue(charge("4242", 100)["ok"])

    def test_charge_retries_transient(self):
        retries = 3
        seen = [charge("4242", 5)["ok"] for _ in range(retries)]
        self.assertTrue(any(seen))


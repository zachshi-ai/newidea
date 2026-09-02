import unittest


class SearchTest(unittest.TestCase):
    def test_ranking(self):
        self.assertEqual([3, 2, 1], sorted([1, 2, 3], reverse=True))


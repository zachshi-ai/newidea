import unittest

from src.cart import add


class CartTest(unittest.TestCase):
    def test_add_appends(self):
        cart = []
        add(cart, 'mug', 12)
        self.assertEqual(cart, [('mug', 12)])

